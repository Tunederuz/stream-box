#!/usr/bin/env python3
"""Inlet: permanent Bluetooth agent (BlueZ, D-Bus), started by start.sh with media-venv's Python (dbus-fast).

Xiaomi remotes (and others) start pairing themselves, or redo it on reconnection: with no agent to answer, BlueZ
refuses ("No agent available") and the remote reconnects in a loop without ever working.
btsetup.py only has an agent during its own "pair" runs. This one accepts, without a code (NoInputNoOutput):
  - trusted devices (already paired once, or marked by btsetup.py);
  - any device during a scan started from the menu or the companion app (PAIRING_FLAG file written by btsetup.py,
    valid for PAIRING_WINDOW seconds);
and refuses the rest: an unknown device in range doesn't pair on its own. Accepted outside a scan: marked as trusted,
so that it reconnects on its own afterwards.
"""
import asyncio, os, time

from dbus_fast import BusType, DBusError, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

AGENT_PATH = "/org/streambox/agent"
PAIRING_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "stream-box-bt-pairing")
PAIRING_WINDOW = 120


def pairing_open():
    try:
        return time.time() - os.path.getmtime(PAIRING_FLAG) < PAIRING_WINDOW
    except OSError:
        return False


class Agent(ServiceInterface):
    def __init__(self, bus):
        super().__init__("org.bluez.Agent1")
        self.bus = bus

    async def device_prop(self, device, name):
        reply = await self.bus.call(Message(destination="org.bluez", path=device, interface="org.freedesktop.DBus.Properties",
                                            member="Get", signature="ss", body=["org.bluez.Device1", name]))
        return reply.body[0].value if reply.message_type == MessageType.METHOD_RETURN else None

    async def check(self, device, what):
        trusted = await self.device_prop(device, "Trusted")
        name = await self.device_prop(device, "Alias") or device
        if trusted or pairing_open():
            print(f"btagent.py: {what} accepted for {name}", flush=True)
            if not trusted:
                await self.bus.call(Message(destination="org.bluez", path=device, interface="org.freedesktop.DBus.Properties",
                                            member="Set", signature="ssv", body=["org.bluez.Device1", "Trusted", Variant("b", True)]))
            return
        print(f"btagent.py: {what} refused for {name} (unknown, no scan in progress)", flush=True)
        raise DBusError("org.bluez.Error.Rejected", "unknown device")

    @method()
    def Release(self):
        pass

    @method()
    async def RequestPinCode(self, device: "o") -> "s":
        await self.check(device, "PIN code")
        return "0000"

    @method()
    async def RequestPasskey(self, device: "o") -> "u":
        await self.check(device, "passkey")
        return 0

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
        pass

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):
        pass

    @method()
    async def RequestConfirmation(self, device: "o", passkey: "u"):
        await self.check(device, "pairing")

    @method()
    async def RequestAuthorization(self, device: "o"):
        await self.check(device, "authorization")

    @method()
    async def AuthorizeService(self, device: "o", uuid: "s"):
        await self.check(device, "service")

    @method()
    def Cancel(self):
        pass


async def register(bus):
    for member, sig, body in (("RegisterAgent", "os", [AGENT_PATH, "NoInputNoOutput"]),
                              ("RequestDefaultAgent", "o", [AGENT_PATH])):
        reply = await bus.call(Message(destination="org.bluez", path="/org/bluez", interface="org.bluez.AgentManager1",
                                       member=member, signature=sig, body=body))
        if reply.message_type == MessageType.ERROR and reply.error_name != "org.bluez.Error.AlreadyExists":
            raise RuntimeError(f"{member}: {reply.error_name} {reply.body}")
    print("btagent.py: Bluetooth agent registered", flush=True)


async def main():
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    bus.export(AGENT_PATH, Agent(bus))

    # bluetoothd restarted (or started after us): register again
    def on_message(msg):
        if msg.member == "NameOwnerChanged" and msg.body and msg.body[0] == "org.bluez" and msg.body[2]:
            asyncio.ensure_future(register_retry())
    async def register_retry():
        for _ in range(30):
            try:
                await register(bus)
                return
            except RuntimeError as e:
                print(f"btagent.py: {e}", flush=True)
                await asyncio.sleep(2)
    bus.add_message_handler(on_message)
    await bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus", interface="org.freedesktop.DBus",
                           member="AddMatch", signature="s",
                           body=["type='signal',sender='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.bluez'"]))
    await register_retry()
    await bus.wait_for_disconnect()


if __name__ == "__main__":
    asyncio.run(main())

# Stream Box Privacy Policy

Stream Box is free software that turns a mini PC plugged into a TV into a Twitch, YouTube and Jellyfin player.
Each box is installed and used by its owner, at home: there is no Stream Box server.

## YouTube account

When the owner connects their YouTube account (a code typed on google.com/device, where Google shows "YouTube on TV"),
the box signs in the way the YouTube app for TVs does, to show on their TV their subscriptions, their recommendations
and how far they got in each video.

- Data read: the subscriptions feed and the home of the account (latest videos: title, thumbnail, channel, date,
  duration, view count), and the watch history's progress.
- Data sent: the playback position of the videos watched on the box, as a YouTube player reports it, so that the
  owner's other screens resume where the TV stopped.
- Where it goes: nowhere other than the box itself and YouTube. The token is kept in the configuration folder of the
  box's user, readable by that user only, and nothing is transmitted, sold or shared with anyone; there is no Stream
  Box server.
- Nothing else is changed on the account: the box does not post, comment, like, subscribe or unsubscribe.
- Removing access: "✕  Disconnect YouTube" in the box menu (Settings → Accounts and libraries → YouTube account) or
  "Disconnect" in its companion app (Settings → YouTube account) deletes the box's token. Access can also be revoked at
  any time from https://myaccount.google.com/permissions ("YouTube on TV").

See also the [YouTube Terms of Service](https://www.youtube.com/t/terms) and the
[Google Privacy Policy](https://policies.google.com/privacy).

## Twitch followed channels (Stream Box Twitch app)

To show the channels the owner follows, the box asks Twitch for **read-only** access (`user:read:follows`), with a
code typed on twitch.tv/activate: through the Twitch account's sign-in (the box presents itself as the Twitch app for
TVs, which also lets Twitch recognize the account on the streams, for subscriptions without ads), or through the
Stream Box Twitch app.

- Data read: the followed channels (name, picture) and which of them are live (title, game, viewers).
- Where it goes: nowhere other than the box itself. The token is kept on the box, readable by its user only; the
  Stream Box app is only an identifier, there is no server behind it and its maintainers see nothing.
- Removing access: "Disconnect" in the companion app (Settings → Followed channels) deletes the box's token. Access
  can also be revoked at any time from Twitch (Settings → Connections).

## Contact

Questions: open an issue on the project repository.

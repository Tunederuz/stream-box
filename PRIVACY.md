# Stream Box Privacy Policy

Stream Box is free software that turns a mini PC plugged into a TV into a Twitch, YouTube and Jellyfin player.
Each box is installed and used by its owner, at home: there is no Stream Box server.

## YouTube account (YouTube Data API)

When the owner connects their YouTube account, the box gets **read-only** access (`youtube.readonly`) to show, on
their TV, the latest videos of the channels they are subscribed to.

- Data read: the account's subscription list (name, identifier and picture of the channels), then the latest public
  videos of these channels (title, thumbnail, date, duration, view count).
- Where it goes: nowhere other than the box itself. It is kept in the configuration folder of the box's user,
  readable by that user only, and is not transmitted, sold or shared with anyone.
- Nothing is changed on the account: the box does not post, comment, subscribe or unsubscribe from anything.
- Removing access: "✕  Disconnect subscriptions" in the box menu (Settings → Accounts and libraries → YouTube account) or "Disconnect" in its
  companion app (Settings → YouTube account) deletes the box's tokens. Access can also be revoked at any time from https://myaccount.google.com/permissions.

The use of data obtained through Google APIs complies with the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the Limited Use requirements.

See also the [YouTube Terms of Service](https://www.youtube.com/t/terms) and the
[Google Privacy Policy](https://policies.google.com/privacy).

## Contact

Questions: open an issue on the project repository.

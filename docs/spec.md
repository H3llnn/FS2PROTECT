# Zeisss SubGate

Maintained by Zeisss. Preserve GPL-3.0 and original credits.

One master bot grants/revokes creator IDs and manages child bots. Each deployment
requires API ID/hash/token. Creators own their bot; ownership follows Telegram bot
ID, not token. Revocation stops all children; regrant requires redeploy, restoring
settings and links. Master can stop/start individual bots while owner is permitted.
No /restart. Active bots resume after server restart. No application bot quota.

Owner-only /setting: database channel by ID, up to four channel/supergroup
ForceSubs by ID, admin IDs, welcome text/photo, ForceSubs text, protection default
off, deletion default 30 minutes/off, deletion notice template {durasi}.
Admins only create single/batch links; privileged users bypass membership.
Users must join every target; show only missing targets with Join Channel/Join
Group buttons (no numbering) and Coba Lagi. Fail closed on membership errors.
One database channel active at a time; each link retains original source channel.
Upload/forward -> storage copy -> permanent link; /batch -> files -> Selesai,
preserving order/captions. Unauthorized uploads receive the agreed denial.
Owner-only broadcast. Deletion notice is separate, editable, deleted with files;
durable per-message jobs survive crashes/restarts. Never delete storage originals.
Owner gets one incident and one recovery notification per unresolved target issue.
Secrets are entered in private master chats; do not auto-delete their messages.

Deployment needs a persistent server volume and encryption key. Existing legacy
links can only be resolved if their original channel is explicitly configured.

# Note (27 Sep, ~17:30) from the session doing the master-requirements work

The app.py / config.py / storage.py / set_secret.py / requirements.txt /
.env.example / README.md copies in this folder taken at 17:12 were NOT the
old 14:18 versions. They were the newer merged versions (commit 97d9094 +
Virtual Try-On routes + background removal + Traditional mode), made at the
user's request between 16:57 and 17:10. Restoring app.py to 97d9094 left it
calling outfit_presentation.occasion_inspiration(), which the current
recommendation modules no longer have, so /api/ai/recommend would crash.

They have been copied back. Backups of what was replaced:
backups/pre_rerestore_*/ . Please coordinate through the user before
restoring files in this project again.

# Second required failure and bounded repair

Focused run 2 stopped at test 34. A request made after Stop was recorded as a
pacing skip instead of being rejected immediately. No network call occurred.
Move the active-intake guard ahead of the skip decision. Also close body
reservations if request charging or authoritative begin-record retention fails;
do not attempt a misleading end-record after journal retention failure.
Preserve the failed assertion and log. Zero major lifecycle runs consumed.

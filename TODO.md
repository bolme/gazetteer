These are some issues discovered that should be addressed but are lower priority.  This is a living document and should be updated as new issues are discovered or items removed as they are fixed.

## Issues

### `gaz tree` help message is misleading
This is output from "gaz tree". the limit was reached because of tho 1000000 entries limit.  However the help says to re-run with --max-seconds 300 for a fuller picture.  This is not correct, the limit is not time based but number of entries based.  The help should be updated to reflect this:

Total (at least, walk stopped early): 53,402 dirs, 946,598 files, 175.0 GB
Stopped at the 1000000 entries limit after 53,402 dirs / 946,598 files. Numbers below are a lower bound. Re-run with --max-seconds 300 for a fuller picture.



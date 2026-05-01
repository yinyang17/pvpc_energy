# Changelog

## [0.3.7] - 2026-05-01
### Improvements
- Increased robustness against UFD API blocking (exponential backoff and User-Agent rotation).
- Adjusted `SCAN_INTERVAL` to 30 minutes and `RANDOM_DELAY_MAX` to 3600 seconds.
- Better handling of empty consumption data lists.

### Note
This version maintains attribution to @yinyang17 as the original author.
# JMComic Source Extension

This official first-party extension adapts the maintained `jmcomic` package to ComicAPNG Plugin
API v1. It performs discovery and source-specific image download/decoding in the Plugin Host. The
extension does not contain a ComicAPNG encoder and does not scrape or reproduce the upstream
protocol.

The MVP uses anonymous access exposed normally by `jmcomic`. It does not automate browsers,
CAPTCHA, anti-bot challenges, paywalls, account restrictions, or DRM. Users are responsible for
accessing and saving only content they are authorized to use.

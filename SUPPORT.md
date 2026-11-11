# Support

Lab Hub is a macOS front door for one developer's own workspace of desktop tools: a launcher for those apps plus a few embedded utilities, maintained by one person in their own time. There is no paid
support and no guaranteed response time.

## Where to ask

| You want | Go to |
|---|---|
| Help running it, or a question about how it works | the README first, then a [GitHub issue](https://github.com/wwds-dev/lab_hub/issues) |
| To report a bug | a GitHub issue with the version in the window title, your macOS version, what you did, what you expected and what happened. Do not paste local paths you do not want public, tokens, or anything from your own projects |
| To report a security problem | [SECURITY.md](SECURITY.md), privately, never in a public issue |
| To suggest a feature | a GitHub issue; `SUGGESTIONS.md` lists what is already considered |

## What to expect

Issues are read **about once a week**; a reply within 7 days is the target, not a promise.
Fixes land when the maintainer has time.

## What Lab Hub is not

- A general launcher you can point at any folder: it expects that workspace's layout (`apps.toml`, `sites.py`, the dashboard catalog). It is published as a reference, and adapting it is up to you.

## Known limits

- macOS only (developed on Apple Silicon); published as source, with no binary release.
- The website checks send one request per listed site; a site shown as unreachable may only be blocking that request.

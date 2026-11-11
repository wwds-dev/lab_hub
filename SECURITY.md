<!-- Owner: enable GitHub's private vulnerability reporting for wwds-dev/lab_hub (Settings > Code security > Private vulnerability reporting); the form linked below does not work until then. Delete this comment afterwards. -->

# Security

Lab Hub is free, open-source software maintained by one person. It starts other programs on your Mac, can install a login item and reads configuration files from the workspace,
so security reports are welcome.

## Report privately

Use GitHub's private report form: **Security > Report a vulnerability** on
<https://github.com/wwds-dev/lab_hub/security/advisories/new>. Please do not open a public issue for a vulnerability.

Include the version in the window title, what you did, and what happened. Leave out real keys, tokens and personal data:
describe them instead.

## What to expect

- **Acknowledgement within 7 days.**
- **A first assessment within 14 days**, and a fix or a written reason within 90 days.
- No bounty, and no service-level promise beyond this: one person keeps this project, in
  their own time. If a deadline slips, the report gets a reply saying so.
- Credit in the CHANGELOG if you want it.

## Supported versions

Only the latest commit on `main` is supported. There are no binary releases; Lab Hub is
distributed as source.

## Scope

In scope: this repository.
Out of scope: vulnerabilities in Qt, PySide6 or Python (report those upstream), in the apps it launches (report those to each app's repository), and problems that need an attacker who already controls your Mac.

# Security Policy

## Reporting a Vulnerability

The Skilluv team takes security seriously. If you discover a security vulnerability, we appreciate your help in disclosing it responsibly.

**Please do NOT open a public GitHub issue for security vulnerabilities.**

### How to report

Send a detailed report to **security@skilluv.com** (or, if that inbox is not yet active, to the maintainer's email listed on the GitHub profile).

Alternatively, use GitHub's [Private Vulnerability Reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) feature on this repository.

### What to include

- A clear description of the vulnerability
- Steps to reproduce (with a proof-of-concept if possible)
- The affected version(s) or commit SHA
- The potential impact
- Your suggested remediation (optional but appreciated)

### What to expect

- **Acknowledgment** within 5 business days
- **Initial assessment** within 10 business days
- **Coordinated disclosure timeline** discussed with the reporter — target 90 days from acknowledgment to public disclosure
- **Credit** in the security advisory unless you request anonymity

### Scope

In scope:
- The code hosted in this repository
- Any deployed instance operated by the Skilluv team (staging, production)

Out of scope:
- Third-party services (Stripe, GitHub, Judge0 upstream, etc.) — please report to the respective vendors
- Denial-of-service attacks against production infrastructure
- Social engineering attacks against Skilluv team members
- Issues in dependencies with existing published CVEs

### Recognition

Reporters of valid vulnerabilities may be listed in a `SECURITY-ACKNOWLEDGMENTS.md` file (with their consent) and, for significant findings, credited in the CVE advisory when applicable.

Thank you for helping keep Skilluv and its community safe.

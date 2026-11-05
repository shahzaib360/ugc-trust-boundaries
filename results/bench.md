# Benchmark results

8,802 browser episodes. 438 attack cases and 51 benign cases (each across 3 site variants: schema.org markup / plain classes / obfuscated classes). The planner is fully injection-susceptible: it obeys any instruction it reads. Confirmation prompts are answered by an attentive user (approves what the task asked for, declines the rest) unless stated otherwise.

## Security and usefulness

| defense | attack success | cross-site goals | same-site goals | answer manipulation | payload reached the planner | benign task success | prompts per benign task | task success under attack |
|---|---|---|---|---|---|---|---|---|
| none | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0 | 100.0% |
| origin-set | 61.6% | 0.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0 | 100.0% |
| detector-regex | 34.2% | 28.6% | 38.5% | 33.3% | 34.2% | 100.0% | 0.0 | 100.0% |
| detector-deberta | 28.8% | 14.3% | 38.5% | 33.3% | 32.9% | 94.1% | 0.0 | 87.0% |
| guard-markup | 22.1% | 38.1% | 3.8% | 66.7% | 100.0% | 100.0% | 0.06 | 100.0% |
| guard-rules | 20.1% | 34.5% | 3.8% | 58.3% | 100.0% | 100.0% | 0.06 | 100.0% |
| guard-full | 9.4% | 19.0% | 3.8% | 0.0% | 100.0% | 100.0% | 0.12 | 100.0% |
| guard-full-body | 11.6% | 25.0% | 3.8% | 0.0% | 100.0% | 100.0% | 0.1 | 100.0% |
| guard-oracle | 2.1% | 0.0% | 3.8% | 0.0% | 100.0% | 100.0% | 0.18 | 100.0% |
| guard-full+origin-set | 2.1% | 0.0% | 3.8% | 0.0% | 100.0% | 100.0% | 0.12 | 100.0% |
| guard-full+mask | 7.3% | 19.0% | 0.0% | 0.0% | 31.5% | 100.0% | 0.12 | 100.0% |

## Attack success by goal

| defense | nav | exfil | email-change | delete | leak-post | buy | answer |
|---|---|---|---|---|---|---|---|
| none | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| origin-set | 0.0% | 0.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| detector-regex | 25.0% | 33.3% | 33.3% | 33.3% | 33.3% | 100.0% | 33.3% |
| detector-deberta | 25.0% | 0.0% | 91.7% | 33.3% | 0.0% | 0.0% | 33.3% |
| guard-markup | 66.7% | 0.0% | 0.0% | 0.0% | 0.0% | 50.0% | 66.7% |
| guard-rules | 60.4% | 0.0% | 0.0% | 0.0% | 0.0% | 50.0% | 58.3% |
| guard-full | 33.3% | 0.0% | 0.0% | 0.0% | 0.0% | 50.0% | 0.0% |
| guard-full-body | 43.8% | 0.0% | 0.0% | 0.0% | 0.0% | 50.0% | 0.0% |
| guard-oracle | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 50.0% | 0.0% |
| guard-full+origin-set | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 50.0% | 0.0% |
| guard-full+mask | 33.3% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

## Attack success by payload placement

| defense | body | hidden | subtle | author |
|---|---|---|---|---|
| none | 100.0% | 100.0% | 100.0% | 100.0% |
| origin-set | 65.2% | 65.2% | 65.2% | 0.0% |
| detector-regex | 4.3% | 4.3% | 100.0% | 0.0% |
| detector-deberta | 13.0% | 34.8% | 43.5% | 0.0% |
| guard-markup | 19.6% | 19.6% | 19.6% | 66.7% |
| guard-rules | 17.4% | 17.4% | 17.4% | 66.7% |
| guard-full | 8.0% | 8.0% | 8.0% | 33.3% |
| guard-full-body | 8.0% | 8.0% | 8.0% | 75.0% |
| guard-oracle | 2.2% | 2.2% | 2.2% | 0.0% |
| guard-full+origin-set | 2.2% | 2.2% | 2.2% | 0.0% |
| guard-full+mask | 5.8% | 5.8% | 5.8% | 33.3% |

## By site variant (attack success / benign success)

| defense | schema | plain | obfuscated |
|---|---|---|---|
| none | 100.0% / 100.0% | 100.0% / 100.0% | 100.0% / 100.0% |
| origin-set | 61.6% / 100.0% | 61.6% / 100.0% | 61.6% / 100.0% |
| detector-regex | 34.2% / 100.0% | 34.2% / 100.0% | 34.2% / 100.0% |
| detector-deberta | 28.8% / 94.1% | 28.8% / 94.1% | 28.8% / 94.1% |
| guard-markup | 2.1% / 100.0% | 32.2% / 100.0% | 32.2% / 100.0% |
| guard-rules | 2.1% / 100.0% | 26.0% / 100.0% | 32.2% / 100.0% |
| guard-full | 2.1% / 100.0% | 7.5% / 100.0% | 18.5% / 100.0% |
| guard-full-body | 7.5% / 100.0% | 8.9% / 100.0% | 18.5% / 100.0% |
| guard-oracle | 2.1% / 100.0% | 2.1% / 100.0% | 2.1% / 100.0% |
| guard-full+origin-set | 2.1% / 100.0% | 2.1% / 100.0% | 2.1% / 100.0% |
| guard-full+mask | 0.0% / 100.0% | 5.5% / 100.0% | 16.4% / 100.0% |

## If the user approves every prompt, or declines every prompt

| defense | attack success (user approves all) | benign success (user declines all) |
|---|---|---|
| guard-markup | 80.8% | 94.1% |
| guard-rules | 80.1% | 94.1% |
| guard-full | 65.8% | 88.2% |
| guard-full-body | 65.8% | 90.2% |
| guard-oracle | 75.3% | 82.4% |
| guard-full+origin-set | 51.1% | 88.2% |
| guard-full+mask | 25.1% | 88.2% |

## Benign success by what the task needs

| defense | first-party | ugc-answer | ugc-control | ugc-link |
|---|---|---|---|---|
| none | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) |
| origin-set | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) |
| detector-regex | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) |
| detector-deberta | 87.5% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) |
| guard-markup | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.33 prompts) | 100.0% (0.33 prompts) |
| guard-rules | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.33 prompts) | 100.0% (0.33 prompts) |
| guard-full | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.67 prompts) | 100.0% (0.67 prompts) |
| guard-full-body | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.33 prompts) | 100.0% (0.67 prompts) |
| guard-oracle | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (1.0 prompts) | 100.0% (1.0 prompts) |
| guard-full+origin-set | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.67 prompts) | 100.0% (0.67 prompts) |
| guard-full+mask | 100.0% (0.0 prompts) | 100.0% (0.0 prompts) | 100.0% (0.67 prompts) | 100.0% (0.67 prompts) |

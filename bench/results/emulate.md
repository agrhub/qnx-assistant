# Benchmark: target `emulate`, AI off, 2026-11-12

| Project | Tier | Lines | Open findings before → after | Rule fixes | AI rounds kept | Build | Tests | Time |
| --- | --- | ---: | --- | ---: | --- | --- | --- | ---: |
| linux-sysmon | medium | 146 | 13 → 7 | 1 | 0/0 | fail (2 errors) | not run | 0.4s |
| inih | easy | 1,343 | 0 → 0 | 0 | 0/0 | pass | pass | 0.6s |
| libyaml | easy | 17,197 | 0 → 0 | 0 | 0/0 | pass | pass | 4.7s |
| iperf3 | medium | 21,274 | 7 → 7 | 0 | 0/0 | pass | pass | 11.8s |
| mosquitto | medium | 116,374 | 11 → 11 | 0 | 0/0 | pass | pass | 16.3s |
| redis | medium | 430,849 | 41 → 40 | 1 | 0/0 | fail (11 errors) | not run | 97.9s |
| htop | hard | 48,950 | 31 → 29 | 1 | 0/0 | fail (7 errors) | not run | 19.1s |

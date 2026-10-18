# ECS WireGuard server: setup and stability notes

Collected while operating a WireGuard server on an ECS instance (Ubuntu, single
phone client, no public IPv6).

## Baseline layout

- Server: `wg0` (`10.66.66.1/24`, `fd42:42:42::1/64`), UDP port from `params` (e.g. 60948)
- Clients: one peer each — `10.66.66.2/32`, `10.66.66.3/32`, ...
- Security group: allow ingress UDP `<port>` from `0.0.0.0/0`
- `wg-quick@wg0` enabled on boot; MASQUERADE to `eth0`, FORWARD accept, `ip_forward=1`

## Client config template

```ini
[Interface]
PrivateKey = ...
Address = 10.66.66.N/32,fd42:42:42::N/128
DNS = 1.1.1.1,1.0.0.1
MTU = 1280

[Peer]
PublicKey = <server public key>
PresharedKey = ...
Endpoint = <EIP>:<port>
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

Key points:

- `AllowedIPs = 0.0.0.0/0` only — drop `::/0` unless the server has public IPv6, otherwise IPv6 traffic enters the tunnel and blackholes.
- `DNS = 1.1.1.1` is the right choice when the goal is reaching blocked sites: the query travels through the tunnel, so the answer is not poisoned. Use 223.5.5.5 for domestic-first use.
- `MTU = 1280` matches the Android default and is safe on mobile. Keep the server `wg0` MTU <= client MTU.
- `PersistentKeepalive = 25` keeps the NAT mapping alive on mobile networks (prevents idle disconnects).

## Stability checklist

1. Keep server and client MTU aligned (e.g. both 1280). A larger server MTU means large packets are dropped client-side and TCP stalls.
2. MSS clamp must only lower, never raise:
   `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -m tcpmss --mss 1241:65535 -j TCPMSS --set-mss 1240`
   Do not use `--clamp-mss-to-pmtu` here: it uses the physical egress MTU (1500) and yields 1460, larger than the tunnel can carry.
3. BBR does not help a WireGuard forwarder — traffic is IP/NAT forwarding, not a local TCP endpoint.
4. Inspect with `wg show wg0 dump` (endpoint / latest handshake / rx-tx), `tcpdump -i wg0` (inner packets), `iptables -L FORWARD -v` (forward counters).
5. `wg0.conf` `PostUp`/`PostDown` must stay inside `[Interface]`; appending them after `[Peer]` makes `wg-quick up` fail.
6. "Connected but unstable" on mobile networks usually means the cross-border UDP path (late-evening jitter/QoS). WireGuard over UDP cannot fix that; consider a TCP-based protocol (Hysteria2/Trojan) if it persists.

## Adding a client without the interactive installer

```bash
PC_PRIV=$(wg genkey); PC_PUB=$(echo "$PC_PRIV" | wg pubkey); PSK=$(wg genpsk)
cat >> /etc/wireguard/wg0.conf <<EOF

### Client name
[Peer]
PublicKey = $PC_PUB
PresharedKey = $PSK
AllowedIPs = 10.66.66.N/32,fd42:42:42::N/128
EOF
wg set wg0 peer "$PC_PUB" preshared-key <(echo "$PSK") allowed-ips 10.66.66.N/32,fd42:42:42::N/128
```

Then write the client config (with `PrivateKey = $PC_PRIV`) and `chmod 600`. Verify with `wg show wg0 dump`.

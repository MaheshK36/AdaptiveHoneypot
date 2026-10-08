#!/bin/sh
set -eu

exposed_subnet=${HONEYPOT_EXPOSED_SUBNET:?}
internal_subnet=${HONEYPOT_INTERNAL_SUBNET:?}
exposed_bridge=${HONEYPOT_EXPOSED_BRIDGE_NAME:?}
forward_chain=HONEYPOT-EXPOSED-EGRESS
input_chain=HONEYPOT-EXPOSED-INPUT

iptables -w -S DOCKER-USER >/dev/null
iptables -w -N "$forward_chain" 2>/dev/null || true
iptables -w -F "$forward_chain"
iptables -w -A "$forward_chain" -d "$internal_subnet" -j RETURN
iptables -w -A "$forward_chain" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -w -A "$forward_chain" -j DROP
iptables -w -C DOCKER-USER -s "$exposed_subnet" -j "$forward_chain" 2>/dev/null || \
    iptables -w -I DOCKER-USER 1 -s "$exposed_subnet" -j "$forward_chain"

iptables -w -N "$input_chain" 2>/dev/null || true
iptables -w -F "$input_chain"
iptables -w -A "$input_chain" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -w -A "$input_chain" -j DROP
iptables -w -C INPUT -i "$exposed_bridge" -s "$exposed_subnet" -j "$input_chain" 2>/dev/null || \
    iptables -w -I INPUT 1 -i "$exposed_bridge" -s "$exposed_subnet" -j "$input_chain"

cleanup() {
    iptables -w -D DOCKER-USER -s "$exposed_subnet" -j "$forward_chain" 2>/dev/null || true
    iptables -w -D INPUT -i "$exposed_bridge" -s "$exposed_subnet" -j "$input_chain" 2>/dev/null || true
    iptables -w -F "$forward_chain" 2>/dev/null || true
    iptables -w -X "$forward_chain" 2>/dev/null || true
    iptables -w -F "$input_chain" 2>/dev/null || true
    iptables -w -X "$input_chain" 2>/dev/null || true
}

trap cleanup INT TERM
while :; do
    sleep 3600 &
    wait $!
done
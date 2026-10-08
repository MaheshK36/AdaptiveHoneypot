FROM alpine:3.20

RUN apk add --no-cache iptables

COPY firewall.sh /usr/local/sbin/firewall.sh
RUN chmod 0755 /usr/local/sbin/firewall.sh

ENTRYPOINT ["/usr/local/sbin/firewall.sh"]
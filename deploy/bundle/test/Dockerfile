# A stand-in for a fresh Ubuntu 24.04 machine with systemd, for the air-gap install test.
# Built with the internet (like installing the OS), then run on a network with no way out.
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends systemd systemd-sysv \
      ca-certificates curl iproute2 iptables kmod util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && systemctl mask getty.target console-getty.service systemd-firstboot.service
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]

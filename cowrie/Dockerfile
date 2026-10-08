FROM cowrie/cowrie:latest

ARG COWRIE_UID=999
ARG COWRIE_GID=999

COPY sitecustomize.py /cowrie/cowrie-env/lib/python3.13/site-packages/sitecustomize.py
COPY session_hook.pth /cowrie/cowrie-env/lib/python3.13/site-packages/session_hook.pth
COPY userdb.txt /cowrie/cowrie-git/etc/userdb.txt

USER ${COWRIE_UID}:${COWRIE_GID}
# ──────────────────────────────────────────────────────────────────────────
# Image Docker du module "comptabilité Omega Soft"
# Construit à partir de l'image officielle Odoo 17.0
# ──────────────────────────────────────────────────────────────────────────
FROM odoo:17.0

LABEL maintainer="abdo.afif2004.12@gmail.com" \
      org.opencontainers.image.title="Omega Soft Compta" \
      org.opencontainers.image.description="Module comptabilité Maroc PCGE pour Odoo 17" \
      org.opencontainers.image.source="https://github.com/abdo-aafif/omega-compta"

USER root

# Dépendances Python additionnelles du module
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copie du module dans le bon dossier d'addons
COPY --chown=odoo:odoo . /mnt/extra-addons/315_v3_gev2_claudeCopieCopie

# Nettoyage des artefacts qui ne doivent PAS finir dans l'image
RUN rm -rf \
    /mnt/extra-addons/315_v3_gev2_claudeCopieCopie/docs5 \
    /mnt/extra-addons/315_v3_gev2_claudeCopieCopie/.git \
    /mnt/extra-addons/315_v3_gev2_claudeCopieCopie/.github \
    /mnt/extra-addons/315_v3_gev2_claudeCopieCopie/.claude \
    /mnt/extra-addons/315_v3_gev2_claudeCopieCopie/__pycache__ \
    /mnt/extra-addons/315_v3_gev2_claudeCopieCopie/Dockerfile \
    /mnt/extra-addons/315_v3_gev2_claudeCopieCopie/docker-compose*.yml \
    && find /mnt/extra-addons/315_v3_gev2_claudeCopieCopie -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# Configuration Odoo staging
COPY odoo.conf /etc/odoo/odoo.conf
RUN chown odoo:odoo /etc/odoo/odoo.conf

# Script de démarrage personnalisé
COPY entrypoint.sh /usr/local/bin/staging-entrypoint.sh
RUN chmod +x /usr/local/bin/staging-entrypoint.sh

USER odoo

EXPOSE 8069 8072

ENTRYPOINT ["/usr/local/bin/staging-entrypoint.sh"]
CMD ["odoo"]

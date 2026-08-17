#!/bin/bash
# Встановлення сервісу генерації документів (docgen, порт 8790) + маршрут /gen-doc у Caddy.
set -e
cd /root

# 1. venv з python-docx (Word-бланки) і openpyxl (Excel-бланки, напр. заявка на авто Maersk)
if [ ! -x /root/docgen-venv/bin/python3 ]; then python3 -m venv /root/docgen-venv; fi
/root/docgen-venv/bin/pip install -q python-docx openpyxl

# 2. шаблони бланків
mkdir -p /root/doc-templates
cp /root/Iryna_Karmazina/doc-templates/*.docx /root/doc-templates/
cp /root/Iryna_Karmazina/doc-templates/*.xlsx /root/doc-templates/

# 3. сервіс
cp /root/Iryna_Karmazina/server/docgen.py /root/docgen.py
cat > /etc/systemd/system/docgen.service <<'UNIT'
[Unit]
Description=Document generation service for Unitex OS (8790)
After=network.target docker.service
[Service]
ExecStart=/root/docgen-venv/bin/python3 /root/docgen.py
Restart=always
RestartSec=10
User=root
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable docgen.service >/dev/null 2>&1
systemctl restart docgen.service
sleep 2
echo "SVC: $(systemctl is-active docgen.service)"

# 4. Caddy: маршрут /gen-doc перед SPA-фолбеком
python3 - <<'PY'
c = open('/root/Caddyfile').read()
if '/gen-doc' in c:
    open('/root/Caddyfile.new','w').write(c); print('CADDY: ALREADY')
else:
    block = "\thandle /gen-doc {\n\t\treverse_proxy 127.0.0.1:8790\n\t}\n"
    i = c.index('\thandle {')
    open('/root/Caddyfile.new','w').write(c[:i] + block + c[i:]); print('CADDY: PATCHED')
PY
cp /root/Caddyfile /root/Caddyfile.bak-$(date +%s)
if docker run --rm -v /root/Caddyfile.new:/etc/caddy/Caddyfile:ro caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/tmp/cv-docgen.log 2>&1; then
  cp /root/Caddyfile.new /root/Caddyfile
  docker restart caddy >/dev/null
  sleep 10
  IP=$(curl -s -4 ifconfig.me)
  echo "UI: $(curl -sk -o /dev/null -w '%{http_code}' https://$IP/)"
  echo "GENDOC_NOAUTH: $(curl -sk -o /dev/null -w '%{http_code}' -X POST https://$IP/gen-doc -H 'Content-Type: application/json' -d '{}')"
else
  echo VALIDATE_FAIL; tail -3 /tmp/cv-docgen.log
fi

# 5. локальний тест заповнення (без запису в базу)
TPL_DIR=/root/doc-templates /root/docgen-venv/bin/python3 - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("docgen", "/root/docgen.py")
dg = importlib.util.module_from_spec(spec); spec.loader.exec_module(dg)
for typ,(gen,_) in dg.TYPES.items():
    data = gen({"date":"2026-07-26","booking":"T","container":"T","truck":"T","num":"T"})
    print("FILL %s: %d bytes" % (typ, len(data)))
PY
echo INSTALL_DONE

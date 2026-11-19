# GitHub Actions และการตั้งค่า production

Push/PR ที่มีปลายทางเป็น `main` จะรัน lint, unit tests, frontend build, dependency audit, สแกน secret แบบปกปิดค่า, ตรวจ Compose และทดสอบ Docker stack ชั่วคราว เมื่อ push เข้า `main` และผ่านทั้งหมดจะ build images สำหรับ Linux amd64 แล้วสแกนก่อนเผยแพร่ `web`, `api`, `rimworld` ไป GHCR เป็น `sha-<SHA40>` และแนบ `release.json` ใน `release-<SHA40>` Deploy ใช้ digest ใน manifest ไม่ได้ตัดสินใจจาก tag ที่เคลื่อนได้

`npm audit` บล็อกความเสี่ยงระดับ high/critical; `pip-audit` บล็อกเมื่อ dependency มี advisory; Trivy บล็อก high/critical ที่มีรุ่นแก้ใน image ของเว็บ/API และรายงานความเสี่ยงของ PostgreSQL และ RimWorld ที่อาศัย upstream แยกกัน ตรวจผลก่อนเปิดบริการสู่ผู้ใช้และติดตาม upstream; อย่าอัปเกรด binary เกมโดยอัตโนมัติเพื่อปิดผลสแกน

## ตั้งค่าเองครั้งเดียว

1. ให้ GitHub Actions ทำงานใน repo และให้ workflow publish สร้าง Releases กับ GHCR packages ได้ ตั้ง visibility/การเข้าถึง package เป็น public หรือตั้ง registry login แบบอ่านอย่างเดียวบน VPS ตรวจว่าตั้ง package สำหรับ repo ถูกต้อง
2. ตั้ง branch protection ให้ Quality gate ผ่านก่อน merge และจำกัดผู้แก้ workflow/ผู้เขียน branch `main` โค้ดจาก PR ไม่ถือ deployment credentials
3. สร้าง GitHub Environment ชื่อ `production` จำกัดให้ deploy จาก `main` และกำหนด Required reviewers หาก plan/repo รองรับ สิ่งนี้ต้องเปิดเองใน GitHub
4. เพิ่ม secrets ใน Environment ตามตาราง และตั้ง `VPS_SSH_PORT` เป็น variable หาก SSH ไม่ใช่พอร์ต 22

| ค่า | ใช้สำหรับ |
| --- | --- |
| `VPS_HOST` | Public IP หรือ DNS ของ VPS |
| `VPS_SSH_USER` | บัญชี deploy เฉพาะงาน ซึ่งไม่ใช่ root |
| `VPS_SSH_PRIVATE_KEY` | Private key ของบัญชี deploy สำหรับ Actions |
| `VPS_SSH_KNOWN_HOSTS` | บรรทัด host key ที่ตรวจ fingerprint จาก VPS/provider ด้วยช่องทางที่เชื่อถือได้ |

5. บน VPS เตรียม checkout และ `sh deploy.sh --prepare` ด้วยผู้ใช้นั้น ให้บัญชีอ่าน checkout, เขียน state และใช้ Docker ได้ Docker group มีสิทธิ์เทียบเท่า root บนเครื่อง ไม่ควรนำบัญชีนี้ไปใช้กับงานอื่น เพิ่ม public key ของ CI ใน `authorized_keys` พร้อม forced command (แทน path ด้วยตำแหน่งจริง):
   ```text
   restrict,command="/absolute/checkout/scripts/ssh-deploy.sh" <public-key>
   ```
   ไฟล์ `scripts/ssh-deploy.sh` ต้อง executable (`chmod 755 scripts/ssh-deploy.sh`) คีย์นี้เรียกได้เฉพาะ protocol ที่รับ release SHA, scope, maintenance และ dry run ไม่มี interactive shell ห้ามปิด host key checking
6. เปิด SSH ให้ runner ที่ตั้งใจใช้งาน และเปิด TCP 25555 ให้ผู้เล่นใน provider firewall คง TCP 10005, 8000 และ 5432 แบบ private ยกเว้น dashboard ที่เลือกเปิดเอง จัดเตรียมตำแหน่งสำรองข้อมูลนอก VPS และตั้ง timezone ตามต้องการ (เวลาใน manifest ใช้ UTC)

## Deploy

เปิด Actions → **Deploy production (manual)** → Run workflow ใส่ SHA จาก GitHub Release แล้วเลือก scope (ใช้ `app` สำหรับย้ายจากรุ่นเดิม หรือ `all` สำหรับ Fresh VPS) เริ่มจาก Dry run ที่เปิดไว้เป็นค่าเริ่มต้น ตรวจ log และเลือก Maintenance เฉพาะตอนอัปเดตเกม รันอีกครั้งโดยปิด Dry run เมื่อต้องการ deploy จริง หากติด approval ให้ผู้ดูแลตรวจ release และ scope ก่อนอนุมัติ

ถ้า Quality gate ไม่ผ่าน ดู job ที่ล้มเหลวแล้วแก้ก่อน publish ถ้า CD ไม่ผ่าน ดูข้อความขั้นตอนที่ล้มเหลว แล้วเปิด `sh scripts/release-status.sh` บน VPS ตรวจ health และ backup อ้างอิง ก่อนใช้ rollback หรือ recovery ตาม [คู่มือดูแลระบบ](operations.md) ไม่มีการตั้งค่า GitHub/VPS หรือเผยแพร่ release จากการเปลี่ยนแปลงใน working copy โดยอัตโนมัติ

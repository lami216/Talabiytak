# مدير صور المنتجات — المرحلة الأولى

تطبيق عربي باتجاه RTL لاستخراج كل الصور الموجودة تحت `xl/media` داخل ملف `xlsx` دون الاعتماد على الورقة أو الخلية، وتطبيعها في الذاكرة، ورفع الصور الفريدة إلى ImageKit، ثم تسميتها وحفظ بيانات المنتجات والبحث عنها وتعديلها وحذفها بأمان.

## التخزين والخصوصية
ImageKit هو مخزن الصور الدائم الوحيد. لا ينشئ التطبيق مجلد `media` أو `uploads` ولا يحفظ الصورة أو Base64 في SQLite؛ قاعدة SQLite تحفظ الأسماء، التجزئة، الأبعاد، وروابط ومعرفات ImageKit فقط. يبقى المفتاح الخاص على الخادم في `.env` ولا يصل للمتصفح. ملف Excel مؤقت ويحذف في النجاح والفشل، والصور لا تكتب إلى القرص.

## إعداد ImageKit
أنشئ حساباً ومشروعاً من لوحة ImageKit، وانسخ Private Key وPublic Key وURL Endpoint إلى `IMAGEKIT_PRIVATE_KEY` و`IMAGEKIT_PUBLIC_KEY` و`IMAGEKIT_URL_ENDPOINT` في `.env`. لا تشارك المفتاح الخاص. عند تدوير المفاتيح حدّث `.env` ثم `pm2 restart product-image-manager --update-env`. إذا حذفت صورة يدوياً من ImageKit سيبقى سجل المنتج لكن ستفشل المعاينة؛ استبدل الصورة من صفحة التعديل.

## تثبيت وتشغيل
```bash
cp env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
mkdir -p /var/lib/product-image-manager
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
اضبط كل قيم `.env` ولا تستخدم القيم التجريبية. سجّل الدخول بالقيمتين `ADMIN_USERNAME` و`ADMIN_PASSWORD`. من «رفع ملف Excel» اختر xlsx، ثم اكتب الاسم تحت الصورة واضغط Enter/الحفظ. ابحث وعدّل من «المنتجات». صفحة الدفعة تتيح تجاهل الصور وتنظيف الصور غير المستخدمة بعد التأكيد.

## التنظيف والاختبارات
```bash
python -m app.cli cleanup-abandoned-imports --dry-run
python -m app.cli cleanup-abandoned-imports
ruff format .
ruff check .
pytest
```
التنظيف يستخدم `ABANDONED_IMPORT_RETENTION_DAYS` وهو آمن للتكرار. الاختبارات تستخدم ImageKit وهمياً ولا تحتاج الإنترنت.

## التشغيل والإدارة
راجع `DEPLOYMENT.md` لإعداد PM2 وNginx وHTTPS والتحديث والنسخ الاحتياطي. السجلات: `pm2 logs product-image-manager`. أخطاء شائعة: فشل البدء يعني غالباً نقص مفاتيح ImageKit أو SECRET_KEY ضعيف؛ 400 عند الرفع يعني ملفاً غير xlsx/ZIP أو تجاوز حد؛ صورة مفقودة تعني حذفها من ImageKit؛ قفل SQLite يعالج عادة بإيقاف العمليات الإضافية لأن النشر مصمم لعملية PM2 واحدة.

المرحلة لا تنشئ طلبات شراء ولا كميات ولا ملفات Excel/PDF نهائية. البنية الخدمية والنماذج المنفصلة تسمح بإضافة `Order` و`OrderItem` لاحقاً دون إعادة كتابة الاستيراد والمنتجات.

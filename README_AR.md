# مدير كتالوج المنتجات والطلبيات

تطبيق FastAPI غير متزامن لاستخراج الصور مباشرة من `xl/media` داخل ملفات XLSX، ومعالجتها في الذاكرة، وحفظها في ImageKit، وإدارة بيانات المنتجات القابلة للبحث في MongoDB Atlas.

## الإعداد

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
cp env.example .env
python -m app.cli init-db
python -m app.cli check-db
uvicorn app.main:app
```

يستخدم التطبيق واجهة PyMongo الرسمية غير المتزامنة `AsyncMongoClient`. لا يستخدم SQLite أو SQLAlchemy أو Alembic أو Motor.

## الطلبيات المؤقتة

من صفحة **الطلبيات** يمكن إنشاء طلبية مسماة، والبحث في الكتالوج، وتحديد الكميات والترتيب ثم تعديلها أو حذفها. تحفظ MongoDB بيانات الطلبية الصغيرة فقط لمدة 30 يومًا، ويحذفها فهرس TTL تلقائيًا. ينشئ رابط التنزيل الثابت ملف Excel جديدًا في الذاكرة من أحدث بيانات الطلبية وصور المنتجات الحالية؛ ولا يخزن التطبيق ملف XLSX على القرص أو في MongoDB.

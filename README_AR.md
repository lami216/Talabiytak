# مدير كتالوج المنتجات — المرحلة الأولى

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

المرحلة الثانية الخاصة بأوامر الشراء والتصدير غير مطبقة بعد. بنية المنتج والصورة مستقلة عن الاستيراد حتى تتمكن عناصر الطلب المستقبلية من حفظ نسخة تاريخية من اسم المنتج والصورة والكمية والترتيب.

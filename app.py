from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from datetime import datetime, timedelta
import os
import smtplib
from email.message import EmailMessage
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from sqlalchemy import text

from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)
from werkzeug.middleware.proxy_fix import ProxyFix

from models import (
    db,
    User,
    Sport,
    Exercise,
    SubscriptionPlan,
    UserSubscription
)
from translations import translate
# =========================================================
# APP
# =========================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "DETACTICA_SECRET_KEY",
    "detactica-local-dev-secret-key"
)
if os.environ.get("DETACTICA_ENV") == "production":
    secret_key = app.config["SECRET_KEY"]
    if len(secret_key) < 32 or secret_key == "detactica-local-dev-secret-key":
        raise RuntimeError("Set DETACTICA_SECRET_KEY to a random secret of at least 32 characters")

app.config["SESSION_COOKIE_SECURE"] = os.environ.get("DETACTICA_SECURE_COOKIES") == "1"
app.config["REMEMBER_COOKIE_SECURE"] = app.config["SESSION_COOKIE_SECURE"]
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"

# Enable only behind one trusted proxy that overwrites these headers.
if os.environ.get("DETACTICA_TRUST_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0)

database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    database_url = "postgresql://" + database_url[len("postgres://"):]
if database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///coachflow.db"
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAIL_SENDER"] = "deetactica@gmail.com"
app.config["CONTACT_PHONE"] = "01055856727"

db.init_app(app)


@app.route("/healthz")
def healthz():
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        db.session.rollback()
        app.logger.exception("Database health check failed")
        return {"status": "unavailable"}, 503
    return {"status": "ok"}

# =========================================================
# LANGUAGE / TRANSLATION
# =========================================================

@app.context_processor
def inject_translation():

    def t(key):

        language = session.get("language", "ar") or "ar"

        if current_user.is_authenticated:
            language = getattr(
                current_user,
                "language",
                language
            ) or language

        return translate(
            key,
            language
        )

    def current_language():

        if current_user.is_authenticated:
            return getattr(
                current_user,
                "language",
                "ar"
            ) or "ar"

        return session.get("language", "ar") or "ar"

    return {
        "t": t,
        "current_language": current_language()
    }
# =========================================================
# LOGIN MANAGER
# =========================================================

login_manager = LoginManager()

login_manager.init_app(app)

login_manager.login_view = "login"
login_manager.login_message = "يجب تسجيل الدخول أولًا."
login_manager.login_message_category = "error"


@login_manager.user_loader
def load_user(user_id):

    return db.session.get(
        User,
        int(user_id)
    )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    current_subscription = None

    if current_user.is_authenticated:

        current_subscription = UserSubscription.query.filter_by(
            user_id=current_user.id,
            status="active"
        ).order_by(
            UserSubscription.id.desc()
        ).first()

    return render_template(
        "index.html",
        current_subscription=current_subscription
    )


# =========================================================
# LOGIN
# =========================================================
@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if current_user.is_authenticated:

        if current_user.role == "admin":

            return redirect(
                url_for("admin")
            )

        return redirect(
            url_for("dashboard")
        )


    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        # =========================
        # REMEMBER ME
        # =========================

        remember = request.form.get(
            "remember"
        ) == "on"


        # =========================
        # VALIDATION
        # =========================

        if not email or not password:

            flash(
                "اكتب البريد الإلكتروني وكلمة المرور.",
                "error"
            )

            return render_template(
                "login.html"
            )


        user = User.query.filter_by(
            email=email
        ).first()


        if not user:

            flash(
                "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
                "error"
            )

            return render_template(
                "login.html"
            )


        if not check_password_hash(
            user.password_hash,
            password
        ):

            flash(
                "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
                "error"
            )

            return render_template(
                "login.html"
            )


        # =========================
        # LOGIN
        # =========================

        login_user(
            user,
            remember=remember
        )


        # =========================
        # ADMIN
        # =========================

        if user.role == "admin":

            return redirect(
                url_for("admin")
            )


        # =========================
        # NEXT PAGE
        # =========================

        next_page = request.args.get(
            "next"
        )

        if next_page:

            return redirect(
                next_page
            )


        return redirect(
            url_for("dashboard")
        )


    return render_template(
        "login.html"
    )
# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if current_user.is_authenticated:

        return redirect(
            url_for("dashboard")
        )

    if request.method == "POST":

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        # =========================
        # NAME VALIDATION
        # =========================

        if len(full_name) < 3:
            flash(
                "الاسم يجب أن يكون 3 أحرف على الأقل.",
                "error"
            )

            return render_template(
                "register.html"
            )

        # يمنع الأسماء التي كلها أرقام
        if full_name.isdigit():
            flash(
                "من فضلك اكتب اسمًا صحيحًا.",
                "error"
            )

            return render_template(
                "register.html"
            )

        # لازم الاسم يحتوي على حروف
        if not any(
                char.isalpha()
                for char in full_name
        ):
            flash(
                "الاسم يجب أن يحتوي على حروف.",
                "error"
            )

            return render_template(
                "register.html"
            )
        phone = request.form.get(
            "phone",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        if (
            not full_name
            or not phone
            or not email
            or not password
        ):

            flash(
                "من فضلك املأ كل البيانات.",
                "error"
            )

            return render_template(
                "register.html"
            )

        phone_digits = "".join(ch for ch in phone if ch.isdigit())

        if not (
            len(phone_digits) == 11
            and phone_digits.startswith(("010", "011", "012", "015"))
        ):
            flash(
                "اكتب رقم موبايل مصري صحيح مكوّن من 11 رقمًا.",
                "error"
            )
            return render_template("register.html")

        if len(password) < 8:
            flash(
                "كلمة المرور يجب أن تكون 8 أحرف على الأقل.",
                "error"
            )

            return render_template(
                "register.html"
            )


        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:

            flash(
                "البريد الإلكتروني مسجل بالفعل.",
                "error"
            )

            return render_template(
                "register.html"
            )

        new_user = User(
            full_name=full_name,
            phone=phone_digits,
            email=email,
            password_hash="",
            role="coach"
        )

        new_user.set_password(password)

        db.session.add(
            new_user
        )

        db.session.commit()

        login_user(
            new_user
        )

        flash(
            "تم إنشاء الحساب بنجاح. اختار الباقة المناسبة.",
            "success"
        )

        return redirect(
            url_for("plans")
        )

    return render_template(
        "register.html"
    )


# =========================================================
# FORGOT / RESET PASSWORD
# =========================================================

def _reset_serializer():
    return URLSafeTimedSerializer(app.config["SECRET_KEY"])

def _send_reset_email(user, reset_url):
    app_password = os.environ.get("DETACTICA_GMAIL_APP_PASSWORD", "").strip()
    if not app_password:
        raise RuntimeError("DETACTICA_GMAIL_APP_PASSWORD is not configured")

    msg = EmailMessage()
    msg["Subject"] = "DeTactica - Password Reset"
    msg["From"] = app.config["MAIL_SENDER"]
    msg["To"] = user.email
    msg.set_content(
        f"مرحبًا {user.full_name},\n\n"
        "وصلنا طلب لتغيير كلمة مرور حسابك في DeTactica.\n"
        "افتح الرابط التالي خلال 30 دقيقة لإنشاء كلمة مرور جديدة:\n"
        f"{reset_url}\n\n"
        "إذا لم تطلب تغيير كلمة المرور، تجاهل هذه الرسالة.\n\n"
        "DeTactica"
    )

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(app.config["MAIL_SENDER"], app_password)
        smtp.send_message(msg)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()

        # Same user-facing response whether the address exists or not.
        if user:
            token = _reset_serializer().dumps(user.email, salt="password-reset")
            reset_url = url_for("reset_password", token=token, _external=True)
            try:
                _send_reset_email(user, reset_url)
            except Exception:
                app.logger.exception("Password reset email failed")
                flash(
                    f"تعذر إرسال الرسالة حاليًا. تواصل معنا على {app.config['CONTACT_PHONE']} أو {app.config['MAIL_SENDER']}.",
                    "error"
                )
                return render_template("forgot_password.html")

        flash(
            "إذا كان البريد مسجلًا لدينا، ستصلك رسالة لاستعادة كلمة المرور.",
            "success"
        )
        return redirect(url_for("login"))

    return render_template("forgot_password.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = _reset_serializer().loads(
            token, salt="password-reset", max_age=1800
        )
    except SignatureExpired:
        flash("انتهت صلاحية رابط الاستعادة. اطلب رابطًا جديدًا.", "error")
        return redirect(url_for("forgot_password"))
    except BadSignature:
        flash("رابط الاستعادة غير صالح.", "error")
        return redirect(url_for("forgot_password"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("رابط الاستعادة غير صالح.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(password) < 8:
            flash("كلمة المرور يجب أن تكون 8 أحرف على الأقل.", "error")
            return render_template("reset_password.html")
        if password != confirm_password:
            flash("كلمتا المرور غير متطابقتين.", "error")
            return render_template("reset_password.html")

        user.set_password(password)
        db.session.commit()
        flash("تم تغيير كلمة المرور بنجاح. يمكنك تسجيل الدخول الآن.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html")


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
@login_required
def logout():

    logout_user()

    flash(
        "تم تسجيل الخروج بنجاح.",
        "success"
    )

    return redirect(
        url_for("login")
    )


# =========================================================
# PLANS
# =========================================================

@app.route("/plans")
@login_required
def plans():

    all_plans = SubscriptionPlan.query.filter_by(
        is_active=True
    ).all()

    current_subscription = UserSubscription.query.filter_by(
        user_id=current_user.id,
        status="active"
    ).order_by(
        UserSubscription.id.desc()
    ).first()

    current_plan_id = None

    if current_subscription:

        current_plan_id = (
            current_subscription.plan_id
        )

    return render_template(
        "plans.html",
        plans=all_plans,
        current_plan_id=current_plan_id
    )


# =========================================================
# SUBSCRIBE
# =========================================================

@app.route(
    "/subscribe/<int:plan_id>"
)
@login_required
def subscribe(plan_id):

    selected_plan = SubscriptionPlan.query.get_or_404(
        plan_id
    )

    old_subscriptions = UserSubscription.query.filter_by(
        user_id=current_user.id,
        status="active"
    ).all()

    for subscription in old_subscriptions:

        subscription.status = "cancelled"

    start_time = datetime.utcnow()

    new_subscription = UserSubscription(
        user_id=current_user.id,
        plan_id=selected_plan.id,
        start_date=start_time,
        end_date=(
            start_time
            + timedelta(
                days=selected_plan.duration_days
            )
        ),
        status="active"
    )

    db.session.add(
        new_subscription
    )

    db.session.commit()

    flash(
        f"تم الاشتراك في باقة {selected_plan.name} بنجاح.",
        "success"
    )

    return redirect(
        url_for("account")
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    sports = Sport.query.filter_by(
        is_active=True
    ).all()

    return render_template(
        "dashboard.html",
        user=current_user,
        sports=sports
    )


# =========================================================
# SPORT DETAILS
# =========================================================

@app.route("/sport/<slug>")
@login_required
def sport_details(slug):

    sport = Sport.query.filter_by(
        slug=slug,
        is_active=True
    ).first_or_404()

    exercises = Exercise.query.filter_by(
        sport_id=sport.id,
        is_published=True
    ).order_by(
        Exercise.created_at.desc()
    ).all()

    return render_template(
        "sport_details.html",
        sport=sport,
        exercises=exercises
    )


# =========================================================
# BOARD MENU
# =========================================================

@app.route("/football/board")
@login_required
def board_menu():

    return render_template(
        "board_templates.html"
    )


# =========================================================
# TACTICAL BOARD
# =========================================================

@app.route("/football/board/new")
@login_required
def tactical_board():

    return render_template(
        "tactical_board.html"
    )


# =========================================================
# BOARD TEMPLATES
# =========================================================

@app.route("/football/templates")
@login_required
def board_templates():

    return render_template(
        "board_templates.html"
    )


# =========================================================
# AI ASSISTANT
# =========================================================

@app.route("/football/ai-assistant")
@login_required
def board_ai():

    return render_template(
        "board_ai.html"
    )


# =========================================================
# EXERCISES LIBRARY
# =========================================================

@app.route("/football/exercises")
@login_required
def exercises_library():

    football = Sport.query.filter_by(
        slug="football",
        is_active=True
    ).first_or_404()

    exercises = Exercise.query.filter_by(
        sport_id=football.id,
        is_published=True
    ).order_by(
        Exercise.created_at.desc()
    ).all()

    return render_template(
        "exercises.html",
        exercises=exercises,
        sport=football
    )


# =========================================================
# EXERCISE DETAILS
# =========================================================

@app.route(
    "/football/exercises/<int:exercise_id>"
)
@login_required
def exercise_details(exercise_id):

    exercise = Exercise.query.get_or_404(
        exercise_id
    )

    if not exercise.is_published:

        flash(
            "هذا التمرين غير متاح حاليًا.",
            "error"
        )

        return redirect(
            url_for("exercises_library")
        )

    return render_template(
        "exercise_details.html",
        exercise=exercise
    )


# =========================================================
# OPEN EXERCISE ON BOARD
# =========================================================

@app.route(
    "/football/exercises/<int:exercise_id>/board"
)
@login_required
def exercise_board(exercise_id):

    exercise = Exercise.query.get_or_404(
        exercise_id
    )

    if not exercise.is_published:

        flash(
            "هذا التمرين غير متاح حاليًا.",
            "error"
        )

        return redirect(
            url_for("exercises_library")
        )

    return render_template(
        "tactical_board.html",
        exercise=exercise
    )


# =========================================================
# ACCOUNT
# =========================================================

@app.route("/account")
@login_required
def account():

    current_subscription = UserSubscription.query.filter_by(
        user_id=current_user.id,
        status="active"
    ).order_by(
        UserSubscription.id.desc()
    ).first()

    return render_template(
        "account.html",
        user=current_user,
        current_subscription=current_subscription
    )

# =========================================================
# CHANGE LANGUAGE
# =========================================================

@app.route(
    "/change-language",
    methods=["POST"]
)
@login_required
def change_language():

    language = request.form.get(
        "language",
        "ar"
    ).strip().lower()

    # نقبل اللغتين فقط
    if language not in ["ar", "en"]:

        flash(
            "اختيار اللغة غير صحيح.",
            "error"
        )

        return redirect(
            url_for("account")
        )

    # حفظ اللغة في حساب المستخدم وفي الجلسة الحالية
    current_user.language = language
    session["language"] = language

    db.session.commit()

    if language == "en":

        flash(
            "Language changed to English.",
            "success"
        )

    else:

        flash(
            "تم تغيير اللغة إلى العربية.",
            "success"
        )

    return redirect(
        url_for("account")
    )
# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
@login_required
def admin():

    if current_user.role != "admin":

        flash(
            "غير مسموح بالدخول لهذه الصفحة.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    users_count = User.query.count()
    sports_count = Sport.query.count()
    exercises_count = Exercise.query.count()
    plans_count = SubscriptionPlan.query.count()

    latest_users = User.query.order_by(
        User.created_at.desc()
    ).limit(
        5
    ).all()

    latest_exercises = Exercise.query.order_by(
        Exercise.created_at.desc()
    ).limit(
        5
    ).all()

    return render_template(
        "admin.html",
        users_count=users_count,
        sports_count=sports_count,
        exercises_count=exercises_count,
        plans_count=plans_count,
        latest_users=latest_users,
        latest_exercises=latest_exercises
    )


# =========================================================
# ADMIN EXERCISES
# =========================================================

@app.route("/admin/exercises")
@login_required
def admin_exercises():

    if current_user.role != "admin":

        flash(
            "غير مسموح بالدخول لهذه الصفحة.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    exercises = Exercise.query.order_by(
        Exercise.created_at.desc()
    ).all()

    return render_template(
        "admin_exercises.html",
        exercises=exercises
    )


# =========================================================
# ADMIN ADD EXERCISE
# =========================================================

@app.route(
    "/admin/exercises/add",
    methods=["GET", "POST"]
)
@login_required
def admin_add_exercise():

    if current_user.role != "admin":

        flash(
            "غير مسموح بالدخول لهذه الصفحة.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    sports = Sport.query.filter_by(
        is_active=True
    ).all()

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        sport_id = request.form.get(
            "sport_id",
            type=int
        )

        if (
            not title
            or not description
            or not sport_id
        ):

            flash(
                "اسم التمرين والوصف والرياضة بيانات مطلوبة.",
                "error"
            )

            return render_template(
                "admin_add_exercise.html",
                sports=sports
            )

        sport = db.session.get(
            Sport,
            sport_id
        )

        if not sport:

            flash(
                "الرياضة المختارة غير موجودة.",
                "error"
            )

            return render_template(
                "admin_add_exercise.html",
                sports=sports
            )

        new_exercise = Exercise(
            title=title,
            description=description,
            sport_id=sport_id,

            category=request.form.get(
                "category",
                ""
            ).strip() or None,

            goal=request.form.get(
                "goal",
                ""
            ).strip() or None,

            level=request.form.get(
                "level",
                ""
            ).strip() or None,

            age_group=request.form.get(
                "age_group",
                ""
            ).strip() or None,

            duration_minutes=request.form.get(
                "duration_minutes",
                type=int
            ),

            players_count=request.form.get(
                "players_count",
                ""
            ).strip() or None,

            equipment=request.form.get(
                "equipment",
                ""
            ).strip() or None,

            image_filename=request.form.get(
                "image_filename",
                ""
            ).strip() or None,

            video_url=request.form.get(
                "video_url",
                ""
            ).strip() or None,

            is_published=(
                request.form.get(
                    "is_published"
                ) == "on"
            ),

            created_by=current_user.id
        )

        db.session.add(
            new_exercise
        )

        db.session.commit()

        flash(
            "تم إضافة التمرين بنجاح.",
            "success"
        )

        return redirect(
            url_for("admin_exercises")
        )

    return render_template(
        "admin_add_exercise.html",
        sports=sports
    )


# =========================================================
# ADMIN EDIT EXERCISE
# =========================================================

@app.route(
    "/admin/exercises/<int:exercise_id>/edit",
    methods=["GET", "POST"]
)
@login_required
def admin_edit_exercise(exercise_id):

    if current_user.role != "admin":

        flash(
            "غير مسموح بالدخول لهذه الصفحة.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    exercise = Exercise.query.get_or_404(
        exercise_id
    )

    sports = Sport.query.filter_by(
        is_active=True
    ).all()

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        sport_id = request.form.get(
            "sport_id",
            type=int
        )

        if (
            not title
            or not description
            or not sport_id
        ):

            flash(
                "اسم التمرين والوصف والرياضة بيانات مطلوبة.",
                "error"
            )

            return render_template(
                "admin_edit_exercise.html",
                exercise=exercise,
                sports=sports
            )

        sport = db.session.get(
            Sport,
            sport_id
        )

        if not sport:

            flash(
                "الرياضة المختارة غير موجودة.",
                "error"
            )

            return render_template(
                "admin_edit_exercise.html",
                exercise=exercise,
                sports=sports
            )

        exercise.title = title
        exercise.description = description
        exercise.sport_id = sport_id

        exercise.category = request.form.get(
            "category",
            ""
        ).strip() or None

        exercise.goal = request.form.get(
            "goal",
            ""
        ).strip() or None

        exercise.level = request.form.get(
            "level",
            ""
        ).strip() or None

        exercise.age_group = request.form.get(
            "age_group",
            ""
        ).strip() or None

        exercise.duration_minutes = request.form.get(
            "duration_minutes",
            type=int
        )

        exercise.players_count = request.form.get(
            "players_count",
            ""
        ).strip() or None

        exercise.equipment = request.form.get(
            "equipment",
            ""
        ).strip() or None

        exercise.image_filename = request.form.get(
            "image_filename",
            ""
        ).strip() or None

        exercise.video_url = request.form.get(
            "video_url",
            ""
        ).strip() or None

        exercise.is_published = (
            request.form.get(
                "is_published"
            ) == "on"
        )

        db.session.commit()

        flash(
            "تم تعديل التمرين بنجاح.",
            "success"
        )

        return redirect(
            url_for("admin_exercises")
        )

    return render_template(
        "admin_edit_exercise.html",
        exercise=exercise,
        sports=sports
    )


# =========================================================
# ADMIN DELETE EXERCISE
# =========================================================

@app.route(
    "/admin/exercises/<int:exercise_id>/delete",
    methods=["POST"]
)
@login_required
def admin_delete_exercise(exercise_id):

    if current_user.role != "admin":

        flash(
            "غير مسموح بتنفيذ هذا الإجراء.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    exercise = Exercise.query.get_or_404(
        exercise_id
    )

    db.session.delete(
        exercise
    )

    db.session.commit()

    flash(
        "تم حذف التمرين بنجاح.",
        "success"
    )

    return redirect(
        url_for("admin_exercises")
    )


# =========================================================
# ADMIN PUBLISH / HIDE EXERCISE
# =========================================================

@app.route(
    "/admin/exercises/<int:exercise_id>/toggle",
    methods=["POST"]
)
@login_required
def admin_toggle_exercise(exercise_id):

    if current_user.role != "admin":

        flash(
            "غير مسموح بتنفيذ هذا الإجراء.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    exercise = Exercise.query.get_or_404(
        exercise_id
    )

    exercise.is_published = (
        not exercise.is_published
    )

    db.session.commit()

    if exercise.is_published:

        flash(
            "تم نشر التمرين في مكتبة التمارين.",
            "success"
        )

    else:

        flash(
            "تم إخفاء التمرين من مكتبة التمارين.",
            "success"
        )

    return redirect(
        url_for("admin_exercises")
    )


# =========================================================
# DEFAULT PLANS
# =========================================================

def create_default_plans():

    default_plans = [

        {
            "name": "مجاني",
            "price": 0,
            "duration_days": 30,
            "features":
                "تمارين محدودة، لوحة تحكم أساسية"
        },

        {
            "name": "الأساسية",
            "price": 99,
            "duration_days": 30,
            "features":
                "تمارين أكثر، متابعة الاشتراك، مزايا إضافية"
        },

        {
            "name": "الاحترافية",
            "price": 199,
            "duration_days": 30,
            "features":
                "كل التمارين، كل الرياضات، مزايا احترافية كاملة"
        }

    ]

    for plan_data in default_plans:

        existing_plan = SubscriptionPlan.query.filter_by(
            name=plan_data["name"]
        ).first()

        if not existing_plan:

            new_plan = SubscriptionPlan(
                **plan_data
            )

            db.session.add(
                new_plan
            )

    db.session.commit()


# =========================================================
# DEFAULT SPORTS
# =========================================================

def create_default_sports():

    default_sports = [

        {
            "name_ar": "كرة القدم",
            "name_en": "Football",
            "slug": "football",
            "icon": "⚽",
            "is_active": True
        },

        {
            "name_ar": "الجيم",
            "name_en": "Gym",
            "slug": "gym",
            "icon": "🏋️",
            "is_active": True
        },

        {
            "name_ar": "كرة السلة",
            "name_en": "Basketball",
            "slug": "basketball",
            "icon": "🏀",
            "is_active": True
        },

        {
            "name_ar": "الكيك بوكسينج",
            "name_en": "Kickboxing",
            "slug": "kickboxing",
            "icon": "🥊",
            "is_active": True
        }

    ]

    for sport_data in default_sports:

        existing_sport = Sport.query.filter_by(
            slug=sport_data["slug"]
        ).first()

        if not existing_sport:

            new_sport = Sport(
                **sport_data
            )

            db.session.add(
                new_sport
            )

    db.session.commit()

def create_default_exercises():

    football = Sport.query.filter_by(
        slug="football"
    ).first()

    if not football:
        return

    default_exercises = [

        {
            "title": "تمرين الاستحواذ 4 ضد 2",
            "description":
                "أربعة لاعبين يحتفظون بالكرة ضد لاعبين ضاغطين داخل مساحة محددة. "
                "الهدف هو تحسين سرعة التمرير والتحرك بدون كرة.",
            "category": "تكتيكي",
            "goal": "استحواذ",
            "level": "متوسط",
            "age_group": "ناشئين",
            "duration_minutes": 15,
            "players_count": "6 لاعبين",
            "equipment": "كرة - 4 أقماع",
            "is_published": True
        },

        {
            "title": "تمرين التمرير المثلثي",
            "description":
                "ثلاثة لاعبين في شكل مثلث يتبادلون التمرير مع تغيير المراكز باستمرار. "
                "التمرين يركز على دقة التمرير والاستلام والتحرك.",
            "category": "مهاري",
            "goal": "تمرير",
            "level": "مبتدئ",
            "age_group": "براعم",
            "duration_minutes": 12,
            "players_count": "3 - 6 لاعبين",
            "equipment": "كرات - أقماع",
            "is_published": True
        },

        {
            "title": "تمرين التسديد بعد المراوغة",
            "description":
                "يمر اللاعب بالكرة بين مجموعة أقماع ثم ينهي الهجمة بتسديدة على المرمى. "
                "يهدف إلى تطوير المراوغة والدقة في إنهاء الهجمات.",
            "category": "مهاري",
            "goal": "تسديد",
            "level": "متوسط",
            "age_group": "ناشئين",
            "duration_minutes": 20,
            "players_count": "6 - 10 لاعبين",
            "equipment": "كرات - أقماع - مرمى",
            "is_published": True
        },

        {
            "title": "تمرين الضغط العالي 6 ضد 6",
            "description":
                "فريق يحاول بناء اللعب من الخلف بينما يقوم الفريق الآخر بالضغط العالي "
                "لاستعادة الكرة في أسرع وقت ممكن.",
            "category": "تكتيكي",
            "goal": "ضغط",
            "level": "متقدم",
            "age_group": "شباب",
            "duration_minutes": 25,
            "players_count": "12 لاعب",
            "equipment": "كرات - أقماع - صدريات",
            "is_published": True
        },

        {
            "title": "تمرين الإحماء بالكرة",
            "description":
                "تمرين إحماء ديناميكي باستخدام الكرة يتضمن الجري الخفيف والتمرير "
                "وتغيير الاتجاه والتحرك المستمر.",
            "category": "إحماء",
            "goal": "إحماء",
            "level": "مبتدئ",
            "age_group": "كبار",
            "duration_minutes": 10,
            "players_count": "8 - 16 لاعب",
            "equipment": "كرات - أقماع",
            "is_published": True
        }

    ]

    for exercise_data in default_exercises:

        existing_exercise = Exercise.query.filter_by(
            title=exercise_data["title"],
            sport_id=football.id
        ).first()

        if not existing_exercise:

            new_exercise = Exercise(
                title=exercise_data["title"],
                description=exercise_data["description"],
                sport_id=football.id,
                category=exercise_data["category"],
                goal=exercise_data["goal"],
                level=exercise_data["level"],
                age_group=exercise_data["age_group"],
                duration_minutes=exercise_data["duration_minutes"],
                players_count=exercise_data["players_count"],
                equipment=exercise_data["equipment"],
                is_published=exercise_data["is_published"]
            )

            db.session.add(new_exercise)

    db.session.commit()
def ensure_user_phone_column():
    # Backward-compatible migration for an older local SQLite database.
    # Fresh PostgreSQL databases already get this column from models.py/db.create_all().
    if db.engine.dialect.name != "sqlite":
        return
    columns = db.session.execute(text("PRAGMA table_info(users)")).fetchall()
    column_names = {row[1] for row in columns}
    if "phone" not in column_names:
        db.session.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(30)"))
        db.session.commit()


# =========================================================
# DATABASE SETUP
# =========================================================

with app.app_context():

    db.create_all()
    ensure_user_phone_column()

    create_default_plans()

    create_default_sports()

    create_default_exercises()

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )

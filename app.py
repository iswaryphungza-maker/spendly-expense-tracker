import csv
import io
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Flask, abort, flash, redirect, render_template, request, Response, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import func, extract, or_
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-development-key-change-before-deploy")
database_url = os.environ.get("DATABASE_URL", "sqlite:///expenses.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if os.environ.get("RENDER") or os.environ.get("FLASK_ENV") == "production":
    app.config["SESSION_COOKIE_SECURE"] = True

# CSRF tokens protect forms that change account or expense data.
db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to view your expenses."
login_manager.login_message_category = "info"

CATEGORIES = ["Food", "Transport", "Shopping", "Bills", "Health", "Entertainment", "Education", "Travel", "Other"]
PAYMENT_METHODS = ["Cash", "UPI", "Card", "Bank Transfer", "Other"]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expenses = db.relationship("Expense", backref="owner", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    category = db.Column(db.String(40), nullable=False, default="Other")
    payment_method = db.Column(db.String(40), nullable=False, default="UPI")
    spent_on = db.Column(db.Date, nullable=False, default=date.today, index=True)
    notes = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


def parse_expense_form():
    title = request.form.get("title", "").strip()
    raw_amount = request.form.get("amount", "").strip()
    category = request.form.get("category", "Other")
    payment_method = request.form.get("payment_method", "UPI")
    raw_date = request.form.get("spent_on", "").strip()
    notes = request.form.get("notes", "").strip()
    errors = []
    if not title or len(title) > 120:
        errors.append("Enter a title up to 120 characters.")
    try:
        amount = Decimal(raw_amount)
        if not amount.is_finite() or amount <= 0 or amount > Decimal("9999999999.99"):
            raise InvalidOperation
        amount = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        amount = None
        errors.append("Enter a valid amount greater than zero.")
    try:
        spent_on = date.fromisoformat(raw_date)
    except ValueError:
        spent_on = None
        errors.append("Choose a valid expense date.")
    if category not in CATEGORIES:
        errors.append("Choose a valid category.")
    if payment_method not in PAYMENT_METHODS:
        errors.append("Choose a valid payment method.")
    if len(notes) > 500:
        errors.append("Notes must be 500 characters or fewer.")
    return {"title": title, "amount": amount, "category": category,
            "payment_method": payment_method, "spent_on": spent_on, "notes": notes or None}, errors


def owned_expense_or_404(expense_id):
    # Every read/write is scoped to the authenticated owner.
    expense = Expense.query.filter_by(id=expense_id, user_id=current_user.id).first()
    if expense is None:
        abort(404)
    return expense


def filtered_expenses_query():
    query = Expense.query.filter_by(user_id=current_user.id)
    search = request.args.get("q", "").strip()[:100]
    category = request.args.get("category", "")
    payment = request.args.get("payment", "")
    month = request.args.get("month", "")
    sort = request.args.get("sort", "newest")
    if search:
        query = query.filter(or_(Expense.title.ilike(f"%{search}%"), Expense.notes.ilike(f"%{search}%")))
    if category in CATEGORIES:
        query = query.filter_by(category=category)
    if payment in PAYMENT_METHODS:
        query = query.filter_by(payment_method=payment)
    if month:
        try:
            year, month_num = (int(x) for x in month.split("-", 1))
            if 1 <= month_num <= 12 and 2000 <= year <= 2100:
                query = query.filter(extract("year", Expense.spent_on) == year,
                                     extract("month", Expense.spent_on) == month_num)
        except (ValueError, TypeError):
            month = ""
    if sort == "oldest":
        query = query.order_by(Expense.spent_on.asc(), Expense.id.asc())
    elif sort == "amount_high":
        query = query.order_by(Expense.amount.desc(), Expense.spent_on.desc())
    elif sort == "amount_low":
        query = query.order_by(Expense.amount.asc(), Expense.spent_on.desc())
    else:
        sort = "newest"
        query = query.order_by(Expense.spent_on.desc(), Expense.id.desc())
    return query, {"q": search, "category": category, "payment": payment, "month": month, "sort": sort}


@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        errors = []
        if not 3 <= len(username) <= 40 or not all(ch.isalnum() or ch in "._-" for ch in username):
            errors.append("Username must be 3–40 characters and use letters, numbers, dots, underscores, or hyphens.")
        if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
            errors.append("Enter a valid email address.")
        if len(password) < 10:
            errors.append("Use a password with at least 10 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if User.query.filter(func.lower(User.username) == username.lower()).first():
            errors.append("That username is already taken.")
        if User.query.filter_by(email=email).first():
            errors.append("An account with that email already exists.")
        if errors:
            for error in errors:
                flash(error, "error")
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Your account is ready. Welcome to Spendly!", "success")
            return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        identity = request.form.get("identity", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter(or_(func.lower(User.username) == identity.lower(),
                                     func.lower(User.email) == identity.lower())).first()
        if user and user.check_password(password):
            login_user(user, remember=False)
            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))
        flash("The username/email or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    query, filters = filtered_expenses_query()
    expenses = query.limit(500).all()
    total = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter_by(user_id=current_user.id).scalar()
    today_total = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter_by(user_id=current_user.id, spent_on=date.today()).scalar()
    month_total = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
        Expense.user_id == current_user.id,
        extract("year", Expense.spent_on) == date.today().year,
        extract("month", Expense.spent_on) == date.today().month).scalar()
    count = Expense.query.filter_by(user_id=current_user.id).count()
    category_rows = db.session.query(Expense.category, func.sum(Expense.amount)).filter_by(user_id=current_user.id).group_by(Expense.category).all()
    category_data = {name: float(value or 0) for name, value in category_rows}
    month_rows = db.session.query(extract("year", Expense.spent_on), extract("month", Expense.spent_on), func.sum(Expense.amount)).filter_by(user_id=current_user.id).group_by(extract("year", Expense.spent_on), extract("month", Expense.spent_on)).order_by(extract("year", Expense.spent_on), extract("month", Expense.spent_on)).all()
    monthly_labels = [f"{int(y)}-{int(m):02d}" for y, m, _ in month_rows]
    monthly_values = [float(v or 0) for _, _, v in month_rows]
    return render_template("dashboard.html", expenses=expenses, filters=filters, categories=CATEGORIES,
        payment_methods=PAYMENT_METHODS, total=float(total or 0), today_total=float(today_total or 0),
        month_total=float(month_total or 0), count=count, category_data=category_data,
        monthly_labels=monthly_labels, monthly_values=monthly_values, today=date.today().isoformat())


@app.route("/expense/add", methods=["POST"])
@login_required
def add_expense():
    data, errors = parse_expense_form()
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("dashboard"))
    expense = Expense(user_id=current_user.id, **data)
    db.session.add(expense)
    db.session.commit()
    flash("Expense added successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/expense/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    expense = owned_expense_or_404(expense_id)
    if request.method == "POST":
        data, errors = parse_expense_form()
        if errors:
            for error in errors:
                flash(error, "error")
        else:
            for key, value in data.items():
                setattr(expense, key, value)
            db.session.commit()
            flash("Expense updated.", "success")
            return redirect(url_for("dashboard"))
    return render_template("edit_expense.html", expense=expense, categories=CATEGORIES, payment_methods=PAYMENT_METHODS)


@app.route("/expense/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    expense = owned_expense_or_404(expense_id)
    db.session.delete(expense)
    db.session.commit()
    flash("Expense deleted.", "info")
    return redirect(url_for("dashboard"))


@app.route("/export.csv")
@login_required
def export_csv():
    query, _ = filtered_expenses_query()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Title", "Category", "Payment method", "Amount (INR)", "Notes"])
    for item in query.all():
        writer.writerow([item.spent_on.isoformat(), item.title, item.category, item.payment_method, f"{item.amount:.2f}", item.notes or ""])
    response = Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=spendly-expenses.csv"
    return response


@app.route("/health")
def health():
    return {"status": "ok"}


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))

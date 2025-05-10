from flask import Flask, jsonify, render_template, redirect, request, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
import os
from datetime import datetime
import csv
from io import StringIO
from flask import make_response
import string, random
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "rentmate-secret"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)


class Household(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(8), unique=True, nullable=False)

class HouseholdMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    household_id = db.Column(db.Integer, db.ForeignKey('household.id'))
    role = db.Column(db.String(10))  # 'Owner' or 'Member'

class Chore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    household_id = db.Column(db.Integer, db.ForeignKey('household.id'))
    name = db.Column(db.String(100), nullable=False)
    frequency = db.Column(db.String(20), nullable=False)  # Daily / Weekly / Monthly
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'))
    last_completed = db.Column(db.Date)
    last_completed_by = db.Column(db.Integer, db.ForeignKey('user.id'))


class ChoreLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chore_id = db.Column(db.Integer, db.ForeignKey('chore.id'))
    completed_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    date = db.Column(db.Date)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    household_id = db.Column(db.Integer, db.ForeignKey('household.id'))
    description = db.Column(db.String(255))
    amount = db.Column(db.Float)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    payer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    participants = db.relationship('User', secondary='expense_participant')

class ExpenseParticipant(db.Model):
    __tablename__ = 'expense_participant'
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    share = db.Column(db.Float, default=0)


def generate_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def home():
    return redirect('/login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return redirect('/register')
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registered successfully, now log in')
        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect('/dashboard')
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect('/login')

@app.route('/household', methods=['GET', 'POST'])
@login_required
def household():
    if request.method == 'POST':
        action = request.form['action']
        
        if action == 'create':
            name = request.form['name']
            code = generate_code()
            household = Household(name=name, code=code)
            db.session.add(household)
            db.session.commit()

            member = HouseholdMember(user_id=current_user.id, household_id=household.id, role='Owner')
            db.session.add(member)
            db.session.commit()

            flash(f"Household '{name}' created. Code: {code}")
            return redirect('/dashboard')

        elif action == 'join':
            code = request.form['code']
            household = Household.query.filter_by(code=code).first()
            if not household:
                flash("Invalid code")
                return redirect('/household')
            
            # Check if already a member
            if HouseholdMember.query.filter_by(user_id=current_user.id, household_id=household.id).first():
                flash("You're already a member")
                return redirect('/dashboard')
            
            member = HouseholdMember(user_id=current_user.id, household_id=household.id, role='Member')
            db.session.add(member)
            db.session.commit()

            flash(f"Joined household '{household.name}'")
            return redirect('/dashboard')

    return render_template('household.html')

@app.route('/dashboard')
@login_required
def dashboard():
   
    member = HouseholdMember.query.filter_by(user_id=current_user.id).first()
    
    if not member:
        flash("You need to join or create a household first.")
        return redirect('/household')
    
    household = Household.query.get(member.household_id)
    members = HouseholdMember.query.filter_by(household_id=household.id).all()
    users = {m.user_id: User.query.get(m.user_id).email for m in members}

    return render_template('dashboard.html', user=current_user, household=household, members=members, users=users)

from datetime import date, datetime
@app.route('/chores', methods=['GET', 'POST'])
@login_required
def chores():
    member = HouseholdMember.query.filter_by(user_id=current_user.id).first()
    if not member:
        flash("Join a household first.")
        return redirect('/household')
    
    household = Household.query.get(member.household_id)
    members = HouseholdMember.query.filter_by(household_id=household.id).all()
    
    if request.method == 'POST':
        name = request.form['name']
        frequency = request.form['frequency']

        existing = Chore.query.filter_by(household_id=household.id).all()
        assigned_member_ids = [m.user_id for m in members]
        next_index = len(existing) % len(assigned_member_ids)
        assigned_to = assigned_member_ids[next_index]

        chore = Chore(
            household_id=household.id,
            name=name,
            frequency=frequency,
            assigned_to=assigned_to,
            last_completed=None
        )
        db.session.add(chore)
        db.session.commit()
        flash("Chore added.")
        return redirect('/chores')

    chores = Chore.query.filter_by(household_id=household.id).all()
    users = {m.user_id: User.query.get(m.user_id).email for m in members}
    
    return render_template('chores.html', chores=chores, users=users, user=current_user)


@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    member = HouseholdMember.query.filter_by(user_id=current_user.id).first()
    if not member:
        flash("Join a household first.")
        return redirect('/household')

    household = Household.query.get(member.household_id)
    members = HouseholdMember.query.filter_by(household_id=household.id).all()

    if request.method == 'POST':
       amount = float(request.form['amount'])
       description = request.form['description']
       date = datetime.strptime(request.form['date'], "%Y-%m-%d")
       payer_id = int(request.form['payer'])
       participant_ids = request.form.getlist('participants')

       share_map = {}
       total_percent = 0
       for uid in participant_ids:
        share_str = request.form.get(f'shares_{uid}', '').strip()
        if share_str:
            percent = float(share_str)
            share_map[int(uid)] = percent
            total_percent += percent

        if total_percent > 0:
           normalized_shares = {uid: (pct / total_percent) * amount for uid, pct in share_map.items()}
        else:
           per_share = amount / len(participant_ids)
           normalized_shares = {int(uid): per_share for uid in participant_ids}

        expense = Expense(
          household_id=household.id,
          amount=amount,
          description=description,
          date=date,
          payer_id=payer_id
    )
        db.session.add(expense)
        db.session.flush()

        for uid, share_amt in normalized_shares.items():
          ep = ExpenseParticipant(expense_id=expense.id, user_id=uid, share=share_amt)
          db.session.add(ep)

        db.session.commit()
        flash("Expense added with custom shares.")
        return redirect('/expenses')

    expenses = Expense.query.filter_by(household_id=household.id).order_by(Expense.date.desc()).all()
    users = {m.user_id: User.query.get(m.user_id).email for m in members}
    return render_template('expenses.html', expenses=expenses, members=members, users=users, user=current_user)

def simplify_balances(balances):
    import heapq

    creditors = []
    debtors = []

    for uid, amount in balances.items():
        if amount > 0:
            heapq.heappush(creditors, (-amount, uid))  # max heap
        elif amount < 0:
            heapq.heappush(debtors, (amount, uid))     # min heap

    settlements = []
    while creditors and debtors:
        credit_amt, credit_uid = heapq.heappop(creditors)
        debit_amt, debit_uid = heapq.heappop(debtors)

        settle_amount = min(-debit_amt, -credit_amt)
        settlements.append((debit_uid, credit_uid, settle_amount))

        new_credit = credit_amt + settle_amount
        new_debit = debit_amt + settle_amount

        if new_credit != 0:
            heapq.heappush(creditors, (new_credit, credit_uid))
        if new_debit != 0:
            heapq.heappush(debtors, (new_debit, debit_uid))

    return settlements

@app.route('/balances')
@login_required
def balances():
    member = HouseholdMember.query.filter_by(user_id=current_user.id).first()
    if not member:
        flash("Join a household first.")
        return redirect('/household')

    household_id = member.household_id
    members = HouseholdMember.query.filter_by(household_id=household_id).all()
    user_ids = [m.user_id for m in members]
    users = {u.id: u.email for u in User.query.filter(User.id.in_(user_ids)).all()}

    balances = {uid: 0 for uid in user_ids}

    expenses = Expense.query.filter_by(household_id=household_id).all()
    for e in expenses:
        parts = ExpenseParticipant.query.filter_by(expense_id=e.id).all()
        for p in parts:
            balances[p.user_id] -= p.share
        balances[e.payer_id] += e.amount

    
    settlements = simplify_balances(balances)

    return render_template('balances.html', balances=balances, users=users, settlements=settlements)

@app.route('/complete_chore/<int:chore_id>', methods=['POST'])
@login_required
def complete_chore(chore_id):
    chore = Chore.query.get_or_404(chore_id)
    member = HouseholdMember.query.filter_by(user_id=current_user.id).first()

    if chore.household_id != member.household_id:
        flash("Not authorized.")
        return redirect('/chores')

    members = HouseholdMember.query.filter_by(household_id=chore.household_id).all()
    user_ids = [m.user_id for m in members]
    current_index = user_ids.index(chore.assigned_to)
    next_index = (current_index + 1) % len(user_ids)
    chore.assigned_to = user_ids[next_index]

    chore.last_completed = datetime.utcnow()
    chore.last_completed_by = current_user.id

    db.session.commit()
    flash("Chore marked as done and rotated.")
    return redirect('/chores')

@app.route('/calendar')
@login_required
def calendar():
    return render_template('calendar.html', user=current_user)

@app.route('/api/calendar_data')
@login_required
def calendar_data():
    member = HouseholdMember.query.filter_by(user_id=current_user.id).first()
    if not member:
        return jsonify([])

    household_id = member.household_id
    chores = Chore.query.filter_by(household_id=household_id).all()
    expenses = Expense.query.filter_by(household_id=household_id).all()

    events = []

    for chore in chores:
        if chore.last_completed:
            events.append({
                'title': f"✅ {chore.name}",
                'start': chore.last_completed.strftime('%Y-%m-%d'),
                'color': 'green'
            })

    for expense in expenses:
        events.append({
            'title': f"💰 {expense.description} - ${expense.amount}",
            'start': expense.date.strftime('%Y-%m-%d'),
            'color': 'blue'
        })

    return jsonify(events)

@app.route('/history')
@login_required
def history():
    member = HouseholdMember.query.filter_by(user_id=current_user.id).first()
    if not member:
        return redirect(url_for('dashboard'))

    household_id = member.household_id

    chores = Chore.query.filter(
        Chore.household_id == household_id,
        Chore.last_completed.isnot(None)
    ).order_by(Chore.last_completed.desc()).all()

    expenses = Expense.query.filter_by(household_id=household_id).order_by(Expense.date.desc()).all()

    users = {u.id: u.email for u in User.query.all()}

    return render_template('history.html', chores=chores, expenses=expenses, users=users)

@app.route('/export_csv')
@login_required
def export_csv():
    member = HouseholdMember.query.filter_by(user_id=current_user.id).first()
    if not member:
        return redirect(url_for('dashboard'))

    household_id = member.household_id
    chores = Chore.query.filter_by(household_id=household_id).all()
    expenses = Expense.query.filter_by(household_id=household_id).all()
    users = {u.id: u.email for u in User.query.all()}

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow(['Type', 'Name/Description', 'Amount', 'Date', 'Completed/Paid By'])

    for chore in chores:
        if chore.last_completed:
            writer.writerow(['Chore', chore.name, '', chore.last_completed.strftime('%Y-%m-%d'), users.get(chore.last_completed_by, 'Unknown')])

    for expense in expenses:
        writer.writerow(['Expense', expense.description, expense.amount, expense.date.strftime('%Y-%m-%d'), users.get(expense.payer_id, 'Unknown')])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=rentmate_history.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

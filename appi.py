from flask import Flask, render_template, redirect,  send_file, url_for, flash, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TimeField, TextAreaField, IntegerField, SubmitField
from wtforms.validators import DataRequired
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from flask_mail import Mail, Message
from PIL import Image, ImageDraw, ImageFont
import base64
import io
import os
from flask_migrate import Migrate




# Configuración de la aplicación Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = 'una_clave_secreta_muy_segura'
app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://neondb_owner:npg_EeSaUC82JorQ@ep-restless-water-a5aah6ni-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}  # Evita desconexiones inesperadas



# Inicializar la base de datos
db = SQLAlchemy(app)
migrate = Migrate(app, db)


# Inicializar Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Definir modelos de la base de datos
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(64), nullable=False)  # 'admin' o 'consultor'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)  # Hora de inicio
    end_time = db.Column(db.Time, nullable=False)    # Hora de término
    reason = db.Column(db.String(256), nullable=False)
    people = db.Column(db.Integer, nullable=False)
    contact = db.Column(db.String(64), nullable=False)

    # Método para convertir el objeto Reservation en un diccionario
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'date': self.date.isoformat(),  # Convertir fecha a string
            'start_time': self.start_time.strftime('%H:%M'),
            'end_time': self.end_time.strftime('%H:%M'),
            'reason': self.reason,
            'people': self.people,
            'contact': self.contact
        }

# Definir formularios
class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = StringField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class ReservationForm(FlaskForm):
    name = StringField('Reservation Name', validators=[DataRequired()])
    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()])
    time = TimeField('Time', format='%H:%M', validators=[DataRequired()])
    reason = TextAreaField('Reason', validators=[DataRequired()])
    people = IntegerField('Number of People', validators=[DataRequired()])
    contact = StringField('Contact Number', validators=[DataRequired()])
    submit = SubmitField('Add Reservation')

# Configurar Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Rutas de la aplicación
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')  # Mostrar la página de login
    elif request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return jsonify({
                'success': True,
                'role': user.role  # Devuelve el rol del usuario
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Usuario o contraseña incorrectos'
            })

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('consultor_dashboard'))
    return render_template('admin_dashboard.html')

@app.route('/admin/dashboard/data')
@login_required
def admin_dashboard_data():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'No tienes permisos'}), 403
      # Ordenar por fecha y hora de inicio
    reservations = Reservation.query.order_by(Reservation.date, Reservation.start_time).all()
    return jsonify([reservation.to_dict() for reservation in reservations])

@app.route('/consultor/dashboard')
@login_required
def consultor_dashboard():
    return render_template('consultor_dashboard.html')

@app.route('/consultor/dashboard/data')
@login_required
def consultor_dashboard_data():
    reservations = Reservation.query.order_by(Reservation.date, Reservation.start_time).all()
    return jsonify([reservation.to_dict() for reservation in reservations])

@app.route('/add_reservation')
@login_required
def show_add_reservation_form():
    return render_template('add_reservation.html')

@app.route('/add_reservation', methods=['POST'])
@login_required
def add_reservation():
    if not request.is_json:  # Verificar que la solicitud sea JSON
        return jsonify({
            'success': False,
            'message': 'El contenido debe ser JSON'
        }), 415

    data = request.get_json()  # Obtener los datos JSON enviados desde el frontend

    # Validar que todos los campos estén presentes
    required_fields = ['name', 'date', 'start_time', 'end_time', 'reason', 'people', 'contact']
    if not all(key in data for key in required_fields):
        return jsonify({
            'success': False,
            'message': 'Faltan campos obligatorios'
        }), 400

    try:
        # Convertir los datos recibidos
        date = datetime.strptime(data.get('date'), '%Y-%m-%d').date()
        start_time = datetime.strptime(data.get('start_time'), '%H:%M').time()
        end_time = datetime.strptime(data.get('end_time'), '%H:%M').time()

        # Verificar si hay conflictos de horario
        conflicting_reservations = Reservation.query.filter(
            Reservation.date == date,
            Reservation.start_time < end_time,
            Reservation.end_time > start_time
        ).all()

        if conflicting_reservations:
            # Sugerir una nueva hora
            last_reservation = conflicting_reservations[-1]
            suggested_start_time = (datetime.combine(date, last_reservation.end_time) + timedelta(hours=2)).time()
            suggested_end_time = (datetime.combine(date, suggested_start_time) + timedelta(hours=2)).time()

            return jsonify({
                'success': False,
                'message': 'Conflicto de horario',
                'suggested_start_time': suggested_start_time.strftime('%H:%M'),
                'suggested_end_time': suggested_end_time.strftime('%H:%M')
            }), 409

        # Crear una nueva reserva
        reservation = Reservation(
            name=data.get('name'),
            date=date,
            start_time=start_time,
            end_time=end_time,
            reason=data.get('reason'),
            people=data.get('people'),
            contact=data.get('contact')
        )
        db.session.add(reservation)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Reservación agregada con éxito'
        })
    except ValueError as e:
        return jsonify({
            'success': False,
            'message': f'Error en el formato de fecha u hora: {str(e)}'
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error al agregar la reservación: {str(e)}'
        }), 500

@app.route('/update_reservation/<int:id>', methods=['PUT'])
@login_required
def update_reservation(id):
    data = request.json
    reservation = db.session.get(Reservation, id)
    if reservation:
        try:
            # Convertir los datos recibidos
            new_start_time = datetime.strptime(data.get('start_time'), '%H:%M').time()
            new_end_time = datetime.strptime(data.get('end_time'), '%H:%M').time()
            new_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date()

            # Verificar si hay conflictos de horario (excluyendo la reserva actual)
            conflicting_reservations = Reservation.query.filter(
                Reservation.date == new_date,
                Reservation.start_time < new_end_time,
                Reservation.end_time > new_start_time,
                Reservation.id != id  # Excluir la reserva actual
            ).all()

            if conflicting_reservations:
                # Construir un mensaje detallado sobre el conflicto
                conflict_message = "Conflicto de horario con las siguientes reservaciones:\n"
                for conflict in conflicting_reservations:
                    conflict_message += (
                        f"Reservación: {conflict.name}, "
                        f"Horario: {conflict.start_time.strftime('%H:%M')} - "
                        f"{conflict.end_time.strftime('%H:%M')}\n"
                    )

                # Sugerir una nueva hora basada en la última reservación conflictiva
                last_reservation = conflicting_reservations[-1]
                suggested_start_time = (datetime.combine(new_date, last_reservation.end_time) + timedelta(minutes=30)).time()
                suggested_end_time = (datetime.combine(new_date, suggested_start_time) + timedelta(hours=2)).time()

                return jsonify({
                    'success': False,
                    'message': conflict_message,
                    'suggested_start_time': suggested_start_time.strftime('%H:%M'),
                    'suggested_end_time': suggested_end_time.strftime('%H:%M')
                }), 409

            # Actualizar la reserva
            reservation.name = data.get('name', reservation.name)
            reservation.date = new_date
            reservation.start_time = new_start_time
            reservation.end_time = new_end_time
            reservation.reason = data.get('reason', reservation.reason)
            reservation.people = data.get('people', reservation.people)
            reservation.contact = data.get('contact', reservation.contact)
            db.session.commit()

            return jsonify({
                "success": True,
                "message": "Reservación actualizada con éxito",
                "reservation": reservation.to_dict()  # Devolver los datos actualizados
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'message': f'Error al modificar la reservación: {str(e)}'
            }), 500
    else:
        return jsonify({"success": False, "message": "Reserva no encontrada"}), 404

@app.route('/delete_reservation/<int:id>', methods=['DELETE'])
@login_required
def delete_reservation(id):
    reservation = db.session.get(Reservation, id)
    if reservation:
        db.session.delete(reservation)
        db.session.commit()
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": "Reserva no encontrada"}), 404

@app.route('/postpone_reservation/<int:id>', methods=['PUT'])
@login_required
def postpone_reservation(id):
    reservation = db.session.get(Reservation, id)
    if reservation:
        try:
            # Calcular la nueva fecha (por ejemplo, posponer al día siguiente)
            new_date = reservation.date + timedelta(days=1)
            new_start_time = reservation.start_time
            new_end_time = reservation.end_time

            # Verificar si hay conflictos de horario en la nueva fecha
            conflicting_reservations = Reservation.query.filter(
                Reservation.date == new_date,
                Reservation.start_time < new_end_time,
                Reservation.end_time > new_start_time
            ).all()

            # Si hay conflictos, buscar un horario disponible
            if conflicting_reservations:
                # Encontrar la última reservación del día
                last_reservation = conflicting_reservations[-1]
                new_start_time = (datetime.combine(new_date, last_reservation.end_time) + timedelta(minutes=30)).time()
                new_end_time = (datetime.combine(new_date, new_start_time) + timedelta(hours=2)).time()

            # Actualizar la reservación con la nueva fecha y hora
            reservation.date = new_date
            reservation.start_time = new_start_time
            reservation.end_time = new_end_time
            db.session.commit()

            return jsonify({
                "success": True,
                "message": "Reservación pospuesta con éxito",
                "new_date": new_date.isoformat(),
                "new_start_time": new_start_time.strftime('%H:%M'),
                "new_end_time": new_end_time.strftime('%H:%M')
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'message': f'Error al posponer la reservación: {str(e)}'
            }), 500
    else:
        return jsonify({"success": False, "message": "Reserva no encontrada"}), 404




@app.route('/generate_invitation/<int:id>', methods=['GET'])
@login_required
def generate_invitation_route(id):
    reservation = db.session.get(Reservation, id)
    if reservation:
        img_base64 = generate_confirmation_invitation(
            name=reservation.name,
            date=reservation.date.strftime('%d de %B, %Y'),  # Formato: "15 de Octubre, 2023"
            time=reservation.start_time.strftime('%I:%M %p'),  # Formato: "10:00 AM"
            people=reservation.people,
            location="Rio Lerma #162, Ciudad de México"  # Cambia esto por la ubicación real
        )
        return jsonify({
            'success': True,
            'img_data': img_base64
        })
    else:
        return jsonify({"success": False, "message": "Reserva no encontrada"}), 404
    

import os
import io
import base64
from PIL import Image, ImageDraw, ImageFont
@app.route('/generate_invite', methods=['GET'])
def generate_invite():
    # Obtener los parámetros de la solicitud
    name = request.args.get('name', 'Invitado')
    date = request.args.get('date', 'Fecha no especificada')
    time = request.args.get('time', 'Hora no especificada')
    people = request.args.get('people', 'Número no especificado')
    location = request.args.get('location', 'Ubicación no especificada')

    # Generar la imagen de la invitación
    img_base64 = generate_confirmation_invitation(name, date, time, people, location)

    # Convertir la imagen base64 a bytes
    img_bytes = base64.b64decode(img_base64)

    # Devolver la imagen como archivo descargable
    return send_file(
        io.BytesIO(img_bytes),
        mimetype='image/png',
        as_attachment=True,
        download_name='invitacion.png'
    )

def generate_confirmation_invitation(name, date, time, people, location):
    # Crear una imagen en blanco
    img = Image.new('RGB', (800, 600), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Ruta relativa del logo
    logo_path = r"C:\Users\SISTEMAS\Desktop\BAO\imagen\Logo.png"

    # Intentar cargar el logo
    if os.path.exists(logo_path):
        logo = Image.open(logo_path)
        logo = logo.resize((150, 150))  # Redimensionar el logo
        img.paste(logo, (20, 20))
    else:
        print("⚠️ Advertencia: No se encontró el logo, se generará la invitación sin logo.")

    # Cargar una fuente
    try:
        font_path = "arial.ttf"  # Cambia por la ruta correcta si es necesario
        font_large = ImageFont.truetype(font_path, 30)
        font_medium = ImageFont.truetype(font_path, 24)
        font_small = ImageFont.truetype(font_path, 20)
    except IOError:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Definir colores
    text_color = (0, 0, 0)  # Negro
    header_color = (0, 0, 139)  # Azul oscuro
    img = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(img)
    # Título
    draw.text((200, 50), "INVITACION A TU EXPERIENCIA EN BAO", font=font_large, fill=header_color)
    logo = Image.open("imagen/logo.png")  # Accede a la imagen en la carpeta del proyecto

    logo = logo.resize((150, 150))  # Ajustar tamaño del logo si es necesario
    img.paste(logo, (325, 90))  # Posición debajo del título


    # Cuerpo del mensaje
    draw.text((20, 200), "Estimado/a", font=font_medium, fill=text_color)  
    draw.text((20, 230), name + ",", font=font_medium, fill=text_color)  # Posición más abajo
    draw.text((20, 255), "Gracias por elegir Bao para disfrutar de una experiencia gastronómica única.", font=font_small, fill=text_color)
    draw.text((20, 280), "Nos complace confirmar tu reservación con los siguientes detalles:", font=font_small, fill=text_color)
    draw.text((20, 330), f"Fecha: {date}", font=font_medium, fill=text_color)
    draw.text((20, 370), f"Hora: {time}", font=font_medium, fill=text_color)
    draw.text((20, 410), f"Número de personas: {people}", font=font_medium, fill=text_color)
    draw.text((20, 450), f"Ubicación: {location}", font=font_medium, fill=text_color)
    draw.text((20, 500), "Para garantizar la mejor experiencia, te pedimos llegar con al menos 10 minutos de anticipación.", font=font_small, fill=text_color)
    draw.text((20, 530), "Si necesitas realizar alguna modificación en tu reserva o tienes requisitos especiales,", font=font_small, fill=text_color)
    draw.text((20, 560), "por favor contáctanos al 5634301271.", font=font_small, fill=text_color)

    # Convertir la imagen a base64
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')


@app.route('/reservation/<int:id>', methods=['GET'])
@login_required
def get_reservation(id):
    reservation = db.session.get(Reservation, id)
    if reservation:
        return jsonify(reservation.to_dict())
    else:
        return jsonify({"success": False, "message": "Reserva no encontrada"}), 404



class User(UserMixin, db.Model):
    __tablename__ = 'user'
    __table_args__ = {'extend_existing': True}  # Permite redefinir la tabla

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(128), unique=True, nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)  # Asegúrate de que tenga suficiente espacio
    role = db.Column(db.String(128), nullable=False)  # 'admin' o 'consultor'

    # Método para establecer la contraseña
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # Método para verificar la contraseña
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)




# Crear la base de datos y ejecutar la aplicación
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Crear un usuario admin y un consultor si no existen
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', role='admin')
            admin.set_password('Admin07')
            db.session.add(admin)
        
        if not User.query.filter_by(username='bao').first():
            consultor = User(username='bao', role='consultor')
            consultor.set_password('bao123')
            db.session.add(consultor)
        
        db.session.commit()
    
    app.run(debug=True)
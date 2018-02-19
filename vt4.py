#!/usr/bin/python
# -*- coding: utf-8 -*-

from flask import Flask, session, redirect, url_for, escape, request, Response, render_template
import sqlite3
import logging
import os
import sys
import time
import datetime
import cgi
import hashlib
from functools import wraps

# Lokitiedosto debuggausta varten
logging.basicConfig(filename=os.path.abspath('../../web/flask.log'),level=logging.DEBUG)
logging.debug("Ajettu ohjelma" + time.strftime('%l:%M%p %Z on %b %d, %Y'))

# Luodaan flask instanssi ja salainen avain
app = Flask(__name__)
app.secret_key = # salainen avain 

# Varmistaa että käyttäjä on kirjautunut, jos ei ole, ohjaa kirjautumissivulle
def auth(f):
	@wraps(f)
	def decorated(*args, **kwargs):
		if not 'logged' in session:
			return redirect(url_for('login'))
		return f(*args, **kwargs)
	return decorated

# Tietokantayhteyden avaaminen
def connect_db():
	try:
		con = sqlite3.connect(os.path.abspath('../../hidden/video'))
		con.row_factory = sqlite3.Row
		# Viite-eheydet käyttöön
		con.execute("PRAGMA foreign_keys = 1")
	except Exception as e:
		logging.debug("Kanta ei aukea")
		# sqliten antama virheilmoitus:
		logging.debug(str(e))
	return con

# Hakee elokuvat ja jäsenet kannasta
def get_members_movies():
	db = connect_db()
	members = []
	movies = []
	try:
		# Jäsenet
		cursor = db.execute("""SELECT Jasen.Nimi AS MemberName, Jasen.JasenID AS MemberID FROM Jasen ORDER BY Jasen.Nimi ASC""")
		for row in cursor.fetchall():
			members.append( dict(name=row['MemberName'], id=row['MemberID']) )
		# Elokuvat
		cursor = db.execute("""SELECT Elokuva.Nimi AS MovieName, Elokuva.ElokuvaID AS MovieID, Elokuva.Julkaisuvuosi AS MovieYear FROM Elokuva ORDER BY Elokuva.Nimi, Elokuva.Julkaisuvuosi ASC""")
		for row in cursor.fetchall():
			movies.append( dict(name=row['MovieName'], year=row['MovieYear'], id=row['MovieId']) )
	except Exception as e:
		logging.debug(str(e))
		members = ""
		movies = ""
	db.close()
	return members, movies

# Etusivu
@app.route('/')
@auth
def front_page():
	# Yhdistä kanta
	db = connect_db()
	try:
		# Kysytään vuokratut elokuvat ja otetaan ne talteen
		cursor = db.execute("""SELECT Elokuva.Nimi, Elokuva.Julkaisuvuosi, Elokuva.ElokuvaID FROM Elokuva
		ORDER BY Elokuva.Nimi, Elokuva.Julkaisuvuosi ASC
		""")
		movies = []
		for row in cursor.fetchall():
			movies.append( dict(name=row[0], year=row[1], id=row[2]) )
		
		# Kysytään vuokraukset ja yhdistetään ne elokuviin
		cursor = db.execute("""SELECT Jasen.Nimi, Vuokraus.VuokrausPVM,
		Vuokraus.PalautusPVM, Vuokraus.Maksettu, Elokuva.ElokuvaID, Jasen.JasenID FROM Jasen, Vuokraus, Elokuva
		WHERE Vuokraus.JasenID = Jasen.JasenID AND Vuokraus.ElokuvaID = Elokuva.ElokuvaID
		ORDER BY Vuokraus.VuokrausPVM, Vuokraus.PalautusPVM ASC
		""")
		rentals = []
		# Yhdistetään vuokraukset elokuviin
		for row in cursor.fetchall():
			rentals.append( dict(member_name=row[0], rental_date=row[1], return_date=row[2],
			paid=row[3], movie_id=row[4], member_id=row[5]) )
		for movie in movies:
			movie['rentals'] = []
			for rental in rentals:
				if rental['movie_id'] == movie['id']:
					movie['rentals'].append(rental)
	except Exception as e:
		logging.debug(str(e))
		movies = ""
	# Suljetaan yhteys kantaan
	db.close()
	# Palautetaan etusivu
	return render_template('etusivu.html', movies=movies)

# Sivu jolla tehdään uusi vuokraus
@app.route('/vuokraus/', methods=['POST', 'GET'])
@auth
def rent():
	errors = False
	# Alustetaan virhekentät ja kentät
	err_messages = {'rental_date':'', 'return_date':'', 'paid':'', 'general':''}	
	fields = {"member":"","movie":"","rental_date":"","return_date":"","paid":""}
	# Varmistetaan onko lomake lähetetty
	if request.method == 'POST':
		# Kysytään lomakkeen tiedot
		for k in fields:
			try:
				fields[k] = request.form[k]
			except KeyError:
				logging.debug("Kenttien lukeminen epäonnistui")
			except Exception as e:
				logging.debug(str(e))
		# Tarkistetaan maksukenttä
		try:
			maksu = float(fields['paid'])
			if maksu < 0:
				errors = True
				err_messages['paid'] = u'Maksun pitää olla positiivinen luku!'
		except ValueError:
			errors = True
			err_messages['paid'] = u'Maksun pitää olla positiivinen luku!'
		# Tarkistetaan päivmäärät
		rental_date = ""
		return_date = ""
		try:
			rental_date = datetime.datetime.strptime(fields['rental_date'], '%Y-%m-%d')
		except ValueError:
			errors = True
			err_messages['rental_date'] = u'Päivämäärän pitää olla muotoa: vvvv-kk-pp.'
		try:
			if not fields['return_date'] or fields['return_date'] == u'Palauttamatta':
				fields['return_date'] = u'Palauttamatta'
			else:
				return_date = datetime.datetime.strptime(fields['return_date'], '%Y-%m-%d')
		except ValueError:
			errors = True
			err_messages['return_date'] = u'Päivämäärän pitää olla muotoa: vvvv-kk-pp.'
		if (return_date and rental_date) and (return_date < rental_date):
			errors =  True
			err_messages['return_date'] = 'Palautus ei voi olla aikaisempi kuin vuokraus!'
		# Jos virheitä ei ole, tehdään muutokset kantaa ja ohjataan etusivulle
		if not errors:
			db = connect_db()
			try:
				cursor = db.execute("""INSERT INTO Vuokraus (JasenID, ElokuvaID, VuokrausPVM, PalautusPVM, Maksettu)
				VALUES (:member_id, :movie_id, :rental_date, :return_date, :paid)
				""", {"member_id":fields['member'], "movie_id":fields['movie'], "rental_date":fields['rental_date'], 
				"return_date":fields['return_date'], "paid":fields['paid']})
				db.commit()
			except Exception as e:
				errors = True
				err_messages['general'] = u'Lisääminen ei onnistunut, yrititkö lisätä vuokrauksen joka on jo olemassa?'
				logging.debug(str(e))
			db.close()
			if not errors:
				return redirect(url_for('front_page'))
	# Muussa tapauksessa haetaan elokuvat ja jäsenet ja palautetaan sivu
	members, movies = get_members_movies()
	return render_template('vuokraus.html', members=members, movies=movies, err_messages=err_messages)

# Sivu jossa muokataan olemassa olevaa vuokrausta
@app.route('/muokkaa/', methods=['POST','GET'])
@auth
def edit_rental():
	# Kysytään vuokrauksen tiedot
	try:
		rental = { 'member_id': request.values["memid"], 'movie_id': request.values["movid"], 'rental_date': request.values["rend"], 'return_date': request.values["retd"], 'paid': request.values["pd"] }
	except:
		return redirect(url_for('front_page'))
	try:
		delete = request.form["delete"]
	except:
		delete = ""
	try:
		save = request.form["save"]
	except:
		save = ""
	# Käyttäjä painoi poistonappia
	if delete:
		db = connect_db()
		try:
			cursor = db.execute("""DELETE FROM Vuokraus WHERE JasenID=:memid AND ElokuvaID=:movid AND VuokrausPVM=:rend AND PalautusPVM=:retd AND Maksettu=:pd""", {'memid':rental['member_id'], 'movid':rental['movie_id'], 'rend':rental['rental_date'], 'retd':rental['return_date'], 'pd':rental['paid'] })
			db.commit()
		except Exception as e:
			logging.debug(str(e))
		db.close()
		return redirect(url_for('front_page'))
	# Jos käyttäjä tallensi muokattuja tietoja, täytyy tietojen oikeillisuus tarkistaa
	errors = False
	err_messages = {'rental_date':'', 'return_date':'', 'paid':'', 'general':''}
	if save:
		fields = {"member":"","movie":"","rental_date":"","return_date":"","paid":""}
		# Varmistetaan että lomake lähetetty
		if request.method == 'POST':
			for k in fields:
				try:
					fields[k] = request.form[k]
				except KeyError:
					logging.debug("Kenttien lukeminen epäonnistui")
				except Exception as e:
					logging.debug(str(e))
		# Tarkistetaan maksu
		try:
			maksu = float(fields['paid'])
			if maksu < 0:
				errors = True
				err_messages['paid'] = u'Maksun pitää olla positiivinen luku!'
		except ValueError:
			errors = True
			err_messages['paid'] = u'Maksun pitää olla positiivinen luku!'
		# Tarkistetaan päivmäärät
		rental_date = ""
		return_date = ""
		try:
			rental_date = datetime.datetime.strptime(fields['rental_date'], '%Y-%m-%d')
		except ValueError:
			errors = True
			err_messages['rental_date'] = u'Päivämäärän pitää olla muotoa: vvvv-kk-pp.'
		try:
			if not fields['return_date'] or fields['return_date'] == u'Palauttamatta':
				fields['return_date'] = u'Palauttamatta'
			else:
				return_date = datetime.datetime.strptime(fields['return_date'], '%Y-%m-%d')
		except ValueError:
			errors = True
			err_messages['return_date'] = u'Päivämäärän pitää olla muotoa: vvvv-kk-pp.'
		if (return_date and rental_date) and (return_date < rental_date):
			errors =  True
			err_messages['return_date'] = 'Palautus ei voi olla aikaisempi kuin vuokraus!'
		# Jos ei ollut virheitä, päivitetään muutokset tietokantaan	
		if not errors:
			db = connect_db()
			try:
				cursor = db.execute("""UPDATE Vuokraus SET JasenID=:member_id, ElokuvaID=:movie_id, VuokrausPVM=:rental_date, PalautusPVM=:return_date, Maksettu=:paid WHERE JasenID=:memid AND ElokuvaID=:movid AND VuokrausPVM=:rend AND PalautusPVM=:retd AND Maksettu=:pd""", {"member_id":fields['member'], "movie_id":fields['movie'], "rental_date":fields['rental_date'], "return_date":fields['return_date'], "paid":fields['paid'],'memid':rental['member_id'], 'movid':rental['movie_id'], 'rend':rental['rental_date'], 'retd':rental['return_date'], 'pd':rental['paid'] })
				db.commit()
			except Exception as e:
				errors = True
				err_messages['general'] = u'Muokkaaminen ei onnistunut, näillä tiedoilla on jo vuokraus.'
				logging.debug(str(e))
			db.close()
			if not errors:
				return redirect(url_for('front_page'))
	# Muuten haetaan jäsenet ja elokuvat ja palautetaan sivu
	members, movies = get_members_movies()
	return render_template("muokkaus.html", members=members, movies=movies, rental=rental, errors=errors, err_messages=err_messages)

# Sivu jossa näytetään jäsenet taulukossa
@app.route("/jasenet/", methods=['POST','GET'])
@auth
def show_members():
	# Avataan yhteys kantaan
	db = connect_db()
	# Kysytään järjestys sessiolta tai linkissä tuodusta parametrista
	try:
		try:
			order = request.values["orderby"]
		except:
			order = ""
		if order == "":
			try:
				order = session['order']
			except:
				order = 'name'
		# Tehdään järjesstyksen mukainen kysely
		if order == 'name':
			cursor = db.execute("""SELECT Nimi AS Name, Osoite AS Address, LiittymisPVM AS Joined, Syntymavuosi AS Born, JasenID as id FROM Jasen ORDER BY Nimi""")
		elif order == 'address':
			cursor = db.execute("""SELECT Nimi AS Name, Osoite AS Address, LiittymisPVM AS Joined, Syntymavuosi AS Born, JasenID as id FROM Jasen ORDER BY Osoite""")
		elif order == 'joined':
			cursor = db.execute("""SELECT Nimi AS Name, Osoite AS Address, LiittymisPVM AS Joined, Syntymavuosi AS Born, JasenID as id FROM Jasen ORDER BY LiittymisPVM""")
		elif order == 'born':
			cursor = db.execute("""SELECT Nimi AS Name, Osoite AS Address, LiittymisPVM AS Joined, Syntymavuosi AS Born, JasenID as id FROM Jasen ORDER BY Syntymavuosi""")
		members = []
		# Otetaan jäsenet talteen
		session['order'] = order
		for row in cursor.fetchall():
			members.append( dict( name=row['Name'],address=row['Address'],joined=row['Joined'],born=row['Born'], memid=row['id'] ) )
		# Kysellään vuokraukset
		rentals = []
		cursor = db.execute("""SELECT JasenID AS memid FROM Vuokraus""")
		for row in cursor.fetchall():
			rentals.append( dict( memid=row['memid'] ) )
		# Yhdistetään vuokraukset jäseniin
		for member in members:
			member['rentals'] = []
			for rental in rentals:
				if rental['memid'] == member['memid']:
					member['rentals'].append(rental)

	except Exception as e:
		members = ""
		logging.debug(e)
	# Suljetaan yhteys kantaan
	db.close()
	# Palautetaan sivu
	return render_template("jasenet.html", members=members)	

# Sivu jolta voi poistaa elokuvia
@app.route('/elokuvat/', methods=['POST', 'GET'])
@auth
def movies():
	# Kysytään lomakkeelta mikä elokuva pitää poistaa
	to_delete = ""
	err = ""
	if request.method == 'POST':
		to_delete = request.form['movie']
	# Yritetään poista jos joku pitää poistaa
	if to_delete:
		try:
			db = connect_db()
			db.execute("""DELETE FROM Elokuva WHERE ElokuvaID=:movid""", {'movid':to_delete})
			db.commit()
			db.close()
		# Annetaan virheilmoitus jos yritetään poistaa vuokattua elokuvaa
		except:
			err = u'Vuokrattua elokuvaa ei voi poistaa!'
	
	# Haetaan elokuvat
	members, movies = get_members_movies()
	# Palautetaan sivu
	return render_template("movies.html", movies=movies, err=err)

# Sivu jolta voi kirjautua järjestelmään
@app.route('/kirjaudu/', methods=['POST', 'GET'])
def login():
	try:
		# Jos käyttäjä on jo kirjautunut, ohjataan etusivulle
		if session['logged']:
			return redirect(url_for('front_page'))
	except:
		pass

	# Kysellään lomakkeelta tiedot
	try:
		user = request.form["user"]
	except:
		user = ""
	try:
		password = request.form["pass"]
	except:
		password = ""
	try:
		submited = request.form["submited"]
	except:
		submited = ""
	err = {'user':"", 'pass':""}
	m = hashlib.sha512()
	key = # salausavain
	m.update(key)
	m.update(password)
	right_pass = # salattu salasana
	# Tarkistetaan annetiinko oikeat tiedot
	if user == # käyttäjätunnus and m.digest() == right_pass:
		session['logged'] = 1
		return redirect(url_for('front_page'))
	# Tarkistetaan oliko virhe käyttäjätunnuksessa
	if user != # käyttäjätunnus 
	and submited == 'Kirjaudu':
		err['user'] = u'Käyttäjätunnusta ei löytynyt'
	# Tarkistetaan oliko virhe salasanassa
	if user == # käyttäjätunnus
	and m.digest() != right_pass and submited == 'Kirjaudu':
		err['pass'] = u'Salasana oli väärä'
	# Palautetaan sivu
	return render_template("kirjaudu.html", err=err)

# Järjestelmästä ulos kirjautuminen
@app.route('/ulos/')
@auth
def logout():
	# Poistetaan kirjautumisesta kertova session muuttuja
	session.pop('logged', None)
	return redirect(url_for('login'))

# Debuggausta varten
if __name__ == '__main__':
	app.debug = True
	app.run(debug=True)

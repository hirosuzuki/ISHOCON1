from flask import Flask, request, abort, session, render_template, redirect
import MySQLdb.cursors
import os
import pathlib
import html
import urllib
import datetime
import json
import memcache

static_folder = pathlib.Path(__file__).resolve().parent / 'public'
print(static_folder)
app = Flask(__name__, static_folder=str(static_folder), static_url_path='')

app.secret_key = os.environ.get('ISHOCON1_SESSION_SECRET', 'showwin_happy')

_config = {
    'db_host': os.environ.get('ISHOCON1_DB_HOST', 'localhost'),
    'db_port': int(os.environ.get('ISHOCON1_DB_PORT', '3306')),
    'db_username': os.environ.get('ISHOCON1_DB_USER', 'ishocon'),
    'db_password': os.environ.get('ISHOCON1_DB_PASSWORD', 'ishocon'),
    'db_database': os.environ.get('ISHOCON1_DB_NAME', 'ishocon1'),
}

mc = memcache.Client(['127.0.0.1:11211'], debug=0)

def config(key):
    if key in _config:
        return _config[key]
    else:
        raise "config value of %s undefined" % key


def db():
    if hasattr(request, 'db'):
        return request.db
    else:
        request.db = MySQLdb.connect(**{
            'host': config('db_host'),
            'port': config('db_port'),
            'user': config('db_username'),
            'passwd': config('db_password'),
            'db': config('db_database'),
            'charset': 'utf8mb4',
            'cursorclass': MySQLdb.cursors.DictCursor,
            'autocommit': True,
        })
        cur = request.db.cursor()
        cur.execute("SET SESSION sql_mode='TRADITIONAL,NO_AUTO_VALUE_ON_ZERO,ONLY_FULL_GROUP_BY'")
        cur.execute('SET NAMES utf8mb4')
        return request.db


@app.teardown_request
def close_db(exception=None):
    if hasattr(request, 'db'):
        request.db.close()


def to_jst(datetime_utc):
    return datetime_utc + datetime.timedelta(hours=9)


def to_utc(datetime_jst):
    return datetime_jst - datetime.timedelta(hours=9)


def authenticate(email, password):
    cur = db().cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email, ))
    user = cur.fetchone()
    if user is None or user.get('password', None) != password:
        abort(401)
    else:
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        session['user_email'] = user['email']


def authenticated():
    if not current_user():
        abort(401)


def current_user():
    if 'user_id' in session:
        user = {
            "id": session['user_id'],
            "name": session['user_name'],
            "email": session['user_email'],
        }
        return user
    else:
        return None


def update_last_login(user_id):
    cur = db().cursor()
    cur.execute('UPDATE users SET last_login = %s WHERE id = %s', (datetime.datetime.now(), user_id,))


def get_comments(product_id):
    cur = db().cursor()
    cur.execute("""
SELECT c.content, u.name
FROM comments as c
INNER JOIN users as u
ON c.user_id = u.id
WHERE c.product_id = {}
ORDER BY c.created_at DESC
LIMIT 5
""".format(product_id))

    return cur.fetchall()


def get_comments_count(product_id):
    cur = db().cursor()
    cur.execute('SELECT count(*) as count FROM comments WHERE product_id = {}'.format(product_id))
    return cur.fetchone()['count']


def buy_product(product_id, user_id):
    cur = db().cursor()
    cur.execute("INSERT INTO histories (product_id, user_id, created_at) VALUES ({}, {}, \'{}\')".format(
        product_id, user_id, to_utc(datetime.datetime.now()).strftime('%Y-%m-%d %H:%M:%S')))


def already_bought(product_id):
    if not current_user():
        return False
    cur = db().cursor()
    cur.execute('SELECT count(*) as count FROM histories WHERE product_id = %s AND user_id = %s',
                (product_id, current_user()['id']))
    return cur.fetchone()['count'] > 0


def create_comment(product_id, user_id, content):
    cur = db().cursor()
    cur.execute("""
INSERT INTO comments (product_id, user_id, content, created_at)
VALUES ({}, {}, '{}', '{}')
""".format(product_id, user_id, content, to_utc(datetime.datetime.now()).strftime('%Y-%m-%d %H:%M:%S')))


@app.errorhandler(401)
def authentication_error(error):
    return render_template('login.html', message='ログインに失敗しました'), 401


@app.errorhandler(403)
def authentication_error(error):
    return render_template('login.html', message='先にログインをしてください'), 403


@app.route('/login')
def get_login():
    session.pop('user_id', None)
    return render_template('login.html', message='ECサイトで爆買いしよう！！！！')


@app.route('/login', methods=['POST'])
def post_login():
    authenticate(request.form['email'], request.form['password'])
    update_last_login(current_user()['id'])
    return redirect('/')


@app.route('/logout')
def get_logout():
    session.pop('user_id', None)
    return redirect('/login')


@app.route('/')
def get_index():
    page = int(request.args.get('page', 0))
    cur = db().cursor()
    cur.execute("""
SELECT p.id, p.name, LEFT(p.description, 70) as description, p.image_path, p.price, s.comments, s.comments_count
FROM products p
LEFT OUTER JOIN product_summary s ON p.id = s.id
ORDER BY id DESC LIMIT 50 OFFSET {}
""".format(page * 50))
    products = cur.fetchall()

    for product in products:
        product['comments'] = json.loads(product['comments'])

    return render_template('index.html', products=products, current_user=current_user())


def get_user_info(user_id):
    cur = db().cursor()
    cur.execute("""
SELECT p.id, p.name, LEFT(p.description, 70) as description, p.image_path, p.price, h.created_at
FROM histories as h
LEFT OUTER JOIN products as p
ON h.product_id = p.id
WHERE h.user_id = {}
ORDER BY h.id DESC
""".format(str(user_id)))

    products = cur.fetchall()

    total_pay = 0
    for product in products:
        total_pay += product['price']
        product['created_at'] = str(to_jst(product['created_at']))

    cur = db().cursor()
    cur.execute('SELECT name FROM users WHERE id = {}'.format(str(user_id)))
    user = cur.fetchone()
    return (products, total_pay, user)


def cache_user_info(user_id):
    key = "us_%s" % user_id
    val = get_user_info(user_id)
    mc.set(key, val, 120)
    return val

def get_cached_user_info(user_id):
    key = "us_%s" % user_id
    val = mc.get(key)
    if not val:
        val = cache_user_info(user_id)
    return val

def uncached_user_info(user_id):
    key = "us_%s" % user_id
    mc.delete(key)

@app.route('/users/<int:user_id>')
def get_mypage(user_id):
    products, total_pay, user = get_cached_user_info(user_id)
    return render_template('mypage.html', products=products, user=user,
                                          total_pay=total_pay, current_user=current_user())


@app.route('/products/<int:product_id>')
def get_product(product_id):
    cur = db().cursor()
    cur.execute('SELECT * FROM products WHERE id = {}'.format(product_id))
    product = cur.fetchone()

    cur = db().cursor()
    cur.execute('SELECT * FROM comments WHERE product_id = {}'.format(product_id))
    comments = cur.fetchall()

    return render_template('product.html',
                           product=product, comments=comments, current_user=current_user(),
                           already_bought=already_bought(product_id))


@app.route('/products/buy/<int:product_id>', methods=['POST'])
def post_products_buy(product_id):
    authenticated()
    user = current_user()
    buy_product(product_id, user['id'])
    cache_user_info(user['id'])

    return redirect("/users/{}".format(current_user()['id']))


@app.route('/comments/<int:product_id>', methods=['POST'])
def post_comments(product_id):
    authenticated()
    create_comment(product_id, current_user()['id'], request.form['content'])
    update_product_summary(product_id)
    return redirect("/users/{}".format(current_user()['id']))

def update_product_summary(id):
    cur = db().cursor()
    comments = get_comments(id)
    comments_count = get_comments_count(id)
    cur.execute('UPDATE product_summary SET comments_count = %s, comments = %s WHERE id = %s', (comments_count, json.dumps(comments), id))

@app.route('/init_product_summary')
def init_product_summary():
    cur = db().cursor()
    cur.execute('DROP TABLE IF EXISTS product_summary')
    cur.execute('CREATE TABLE product_summary (id int, comments_count int, comments text, primary key (id))')

    product_comments = {}
    product_comment_count = {}
    
    cur.execute("SELECT c.product_id, c.content, u.name FROM comments as c INNER JOIN users as u ON c.user_id = u.id ORDER BY c.created_at DESC")
    rows = cur.fetchall()
    for row in rows:
        id = row["product_id"]
        if id not in product_comments:
            product_comments[id] = []
        if id not in product_comment_count:
            product_comment_count[id] = 0
        if len(product_comments[id]) < 5:
            product_comments[id].append({"content": row["content"], "name": row["name"]})
        product_comment_count[id] += 1
    
    cur.executemany('INSERT INTO product_summary (id, comments_count, comments) values (%s, %s, %s)', [(id, product_comment_count[id], json.dumps(product_comments[id])) for id in product_comments])

    return "OK"

@app.route('/init_user_info')
def init_user_info():
    cur = db().cursor()
    cur.execute("SELECT id from users ORDER BY id")
    rows = cur.fetchall()
    for row in rows:
        cache_user_info(row["id"])
    return "OK"

@app.route('/initialize')
def get_initialize():
    cur = db().cursor()
    cur.execute('DELETE FROM users WHERE id > 5000')
    cur.execute('DELETE FROM products WHERE id > 10000')
    cur.execute('DELETE FROM comments WHERE id > 200000')
    cur.execute('DELETE FROM histories WHERE id > 500000')
    init_product_summary()
    init_user_info()
    return ("Finish")


if __name__ == "__main__":
    app.run()

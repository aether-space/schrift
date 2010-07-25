# coding: utf-8
import datetime
import re
import unicodedata

import docutils.core
import docutils.writers.html4css1
import flask
import pygments
import pygments.lexers, pygments.formatters
import werkzeug
from docutils import nodes
from docutils.parsers import rst
from flaskext import sqlalchemy
from sqlalchemy import func, Table
from werkzeug.contrib import atom

DEBUG = True
SECRET_KEY = "XI5auBoeiH2TErtf8Hfi"
SQLALCHEMY_DATABASE_URI = "sqlite:///blog.db"
#SQLALCHEMY_ECHO = True

BLOG_TITLE = "choblog"
BLOG_SUBTITLE = "Tired musings of a chief hacking officer."

app = flask.Flask(__name__)
app.config.from_object(__name__)
db = sqlalchemy.SQLAlchemy(app)

### Models

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    password = db.Column(db.String(80))

    def __init__(self, name):
        self.name = name

    def set_password(self, password):
        self.password = werkzeug.generate_password_hash(password)

    def check_password(self, password):
        return werkzeug.check_password_hash(self.password, password)

    def __repr__(self):
        return "<User '%s'>" % (self.name, )

class Tag(db.Model):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    tag = db.Column(db.String(50), nullable=False, unique=True)

    def __init__(self, name):
        self.tag = name

    def __str__(self):
        return self.tag

    def __repr__(self):
        return "<Tag '%s'>" % (self.tag, )

# Association table for tags
post_tags = Table("post_tags", db.Model.metadata,
    db.Column("post_id", db.Integer, db.ForeignKey("posts.id")),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"))
)

class Post(db.Model):
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    author = sqlalchemy.orm.relationship(User,
                        backref=sqlalchemy.orm.backref("posts", lazy="dynamic"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text)
    html = db.Column(db.Text)
    private = db.Column(db.Boolean)
    pub_date = db.Column(db.DateTime)
    tags = sqlalchemy.orm.relationship("Tag", secondary=post_tags,
                                       backref="posts")

    def __init__(self, author, title, content, html, private=False):
        self.author = author
        self.title = title
        self.content = content
        self.html = html
        self.private = private
        self.pub_date = datetime.datetime.utcnow()

    @werkzeug.cached_property
    def next(self):
        return self.query.filter(Post.pub_date > self.pub_date) \
                         .order_by(Post.pub_date).first()

    @werkzeug.cached_property
    def prev(self):
        return self.query.filter(Post.pub_date < self.pub_date) \
                         .order_by(Post.pub_date.desc()).first()

### ReST helpers

class CodeElement(nodes.General, nodes.FixedTextElement):
    pass

class CodeBlock(rst.Directive):
    """
    Directive for a code block.
    """

    has_content = True
    required_arguments = 1
    optional_arguments = 0
    option_spec = dict()

    def run(self):
        code = u'\n'.join(self.content)
        node = CodeElement(code)
        node['lang'] = self.arguments[0]
        return [node]

rst.directives.register_directive('code-block', CodeBlock)

class Translator(docutils.writers.html4css1.HTMLTranslator):
    def visit_CodeElement(self, node):
        lexer = pygments.lexers.get_lexer_by_name(node["lang"])
        formatter = pygments.formatters.get_formatter_by_name("html")
        code = pygments.highlight(node.rawsource, lexer, formatter)
        self.body.append(self.starttag(node, "div", CLASS="syntax"))
        self.body.append(code)

    def depart_CodeElement(self, node):
        self.body.append("</div>")

class Writer(docutils.writers.html4css1.Writer):
    def __init__(self):
        docutils.writers.html4css1.Writer.__init__(self)
        self.translator_class = Translator

### Helpers

def get_tags(string):
    """
    Given a string with comma-separated tag names, return the
    corresponding `Tag` objects. If a tag cannot be found for a given
    name, a new one will be crated and added to the database session.
    """
    tags = list()
    for name in string.split(","):
        name = name.strip()
        tag = Tag.query.filter_by(tag=name).first()
        if tag is None:
            tag = Tag(name)
            db.session.add(tag)
        tags.append(tag)
    return tags

def slugify(value):
    value = unicodedata.normalize("NFKD", value)
    value = value.translate({0x308: u"e", ord(u"ß"): u"ss"})
    value = value.encode("ascii", "ignore").lower()
    value = re.sub(r'[^a-z\s-]', '', value).strip()
    return re.sub(r'[-\s]+', '-', value)

### Template filters
def datetimeformat(value, format='%H:%M / %d-%m-%Y'):
    return value.strftime(format)

app.jinja_env.filters['datetimeformat'] = datetimeformat

### Views

@app.route("/")
def index():
    return show_entries(1)

@app.route("/<int:page>")
def show_entries(page, tags=None):
    query = Post.query.order_by(Post.pub_date.desc())
    if tags is not None:
        query = Post.query.join(Post.tags).filter(Tag.tag.in_(tags)) \
                .group_by(Post.id) \
                .having(func.count(Post.id) == len(tags))
    if not "user_id" in flask.session:
        query = query.filter(Post.private != True)
    query = query.order_by(Post.pub_date.desc())
    page = query.paginate(page, 10, page != 1)
    return flask.render_template("show_entries.html", page=page)

@app.route("/tagged/<tags>")
def show_entries_for_tag(tags):
    return show_entries(1, tags.split(","))

@app.route("/delete/<slug>")
def delete_entry(slug):
    if not "user_id" in flask.session:
        flask.session["real_url"] = flask.request.url
        return flask.redirect(flask.url_for("login"))
    entry = Post.query.filter_by(slug=slug).first_or_404()
    flask.flash('Post "%s" deleted.' % (entry.title, ))
    db.session.delete(entry)
    db.session.commit()
    return flask.redirect(flask.url_for("index"))

@app.route("/show/<slug>")
def show_entry(slug):
    entry = Post.query.filter_by(slug=slug).first_or_404()
    if entry.private and not "user_id" in flask.session:
        flask.session["real_url"] = flask.request.url
        return flask.redirect(flask.url_for("login"))
    return flask.render_template("show_entry.html", entry=entry)

@app.route("/login")
def login_form():
    return flask.render_template("login.html")

@app.route("/login", methods=["POST"])
def login():
    form = flask.request.form
    user = User.query.filter_by(name=form["name"]).first()
    if user is None or not user.check_password(form["password"]):
        flask.flash("Sorry, try again.")
        return flask.redirect(flask.url_for("login"))
    flask.flash("You have been logged in.")
    flask.session["user_id"] = user.id
    return flask.redirect(flask.session.pop("real_url", flask.url_for("index")))

@app.route("/logout")
def logout():
    flask.session.pop("user_id", None)
    flask.flash("You have been logged out.")
    return flask.redirect(flask.url_for("index"))

@app.route("/add")
def add_entry_form(text="", tags=""):
    if not "user_id" in flask.session:
        flask.session["real_url"] = flask.request.url
        return flask.redirect(flask.url_for("login_form"))
    return flask.render_template("add.html", text=text, tags=tags)

@app.route("/add", methods=["POST"])
def add_entry():
    if not "user_id" in flask.session:
        flask.abort(403)
    form = flask.request.form
    if not form["title"]:
        flask.flash("Sorry, a title is required.")
        return add_entry_form(form["content"], form["tags"])
    parts = docutils.core.publish_parts(form["content"], writer=Writer())
    user = User.query.get(flask.session["user_id"])
    post = Post(title=form["title"], content=form["content"],
                html=parts["body"], author=user)
    post.tags = get_tags(form["tags"])
    post.slug = slugify(form["title"])
    db.session.add(post)
    db.session.commit()
    return flask.redirect(flask.url_for("index"))

@app.route("/edit/<slug>")
def edit_entry_form(slug):
    if not "user_id" in flask.session:
        session.request["real_url"] = flask.request.url
        return flask.redirect(flask.url_for("login"))
    entry = Post.query.filter_by(slug=slug).first_or_404()
    return flask.render_template("edit.html", entry=entry)

@app.route("/save", methods=["POST"])
def save_entry():
    if not "user_id" in flask.session:
        flask.abort(403)
    form = flask.request.form
    try:
        entry = Post.query.get_or_404(int(form["id"]))
    except ValueError:
        flask.abort(404)
    entry.content = form["content"]
    entry.tags = get_tags(form["tags"])
    if not form["title"]:
        flask.flash("Sorry, but a title is required.")
        return flask.render_template("edit.html", entry=entry)
    parts = docutils.core.publish_parts(form["content"], writer=Writer())
    entry.html = parts["body"]
    db.session.commit()
    flask.flash('Post "%s" has been updated.' % (entry.title, ))
    return flask.redirect(flask.url_for("index"))

@app.route("/atom")
def atom_feed():
    feed = atom.AtomFeed(BLOG_TITLE, feed_url=flask.request.url,
                         url=flask.request.host_url,
                         subtitle=BLOG_SUBTITLE)
    query = Post.query.order_by(Post.pub_date.desc())
    if not "user_id" in flask.session:
        query = query.filter(Post.private != True)
    for post in query.limit(10):
        feed.add(post.title, post.html, content_type="html",
                 author=post.author.name,
                 url=flask.url_for("show_entry", slug=post.slug), id=post.id,
                 updated=post.pub_date, published=post.pub_date)
    return feed.get_response()

if __name__ == '__main__':
    import sys
    if sys.argv[1:]:
        app.run(sys.argv[1], int(sys.argv[2]))
    else:
        app.run()

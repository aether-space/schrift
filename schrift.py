# coding: utf-8
import datetime
import functools
import itertools
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
import flask_sqlalchemy as sqlalchemy
from sqlalchemy import func, or_, Table
from werkzeug.contrib import atom

DEBUG = True
SECRET_KEY = "XI5auBoeiH2TErtf8Hfi"
SQLALCHEMY_DATABASE_URI = "sqlite:///blog.db"
#SQLALCHEMY_ECHO = True

BLOG_TITLE = "Spamblog"
BLOG_SUBTITLE = "And now for something completely different"

app = flask.Flask(__name__)
app.config.from_object(__name__)
db = sqlalchemy.SQLAlchemy(app)

### Models

# Association table for users (to look up which blog a user can read)
blog_users = Table("blog_users", db.Model.metadata,
    db.Column("reader_id", db.Integer, db.ForeignKey("users.id")),
    db.Column("author_id", db.Integer, db.ForeignKey("users.id"))
)

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    password = db.Column(db.String(80))
    editor = db.Column(db.Boolean)
    blog_title = db.Column(db.String(100))
    blog_subtitle = db.Column(db.String(100))
    # A list of authors whose blog posts the user can read
    authors = sqlalchemy.orm.relationship("User",
        primaryjoin=(blog_users.columns["reader_id"] == id),
        secondaryjoin=(blog_users.columns["author_id"] == id),
        secondary=blog_users
    )

    def __init__(self, name, password, editor=False):
        self.name = name
        self.editor = editor
        self.set_password(password)

    def set_password(self, password):
        self.password = werkzeug.generate_password_hash(password)

    def check_password(self, password):
        return werkzeug.check_password_hash(self.password, password)

    def __repr__(self):
        if self.editor:
            return "<User '%s' (editor)>" % (self.name, )
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
    slug = db.Column(db.String(255), nullable=False, unique=True)
    summary = db.Column(db.Text)
    summary_html = db.Column(db.Text)
    content = db.Column(db.Text)
    html = db.Column(db.Text)
    private = db.Column(db.Boolean)
    published = db.Column(db.Boolean)
    pub_date = db.Column(db.DateTime)
    tags = sqlalchemy.orm.relationship("Tag", secondary=post_tags,
                                       backref="posts")

    def __init__(self, author, title, summary, summary_html, content, html,
                 private=False, published=True):
        self.author = author
        self.title = title
        self.summary = summary
        self.summary_html = summary_html
        self.content = content
        self.html = html
        self.private = private
        self.published = published
        self.pub_date = datetime.datetime.utcnow()

    def get_previous(self, same_author=False):
        query = self.query.filter(Post.pub_date > self.pub_date)
        if not "user_id" in flask.session:
            query = query.filter(Post.private != True)
        if same_author:
            query = query.filter(Post.author == self.author)
        return query.order_by(Post.pub_date).first()

    def get_next(self, same_author=False):
        query = self.query.filter(Post.pub_date < self.pub_date)
        if not "user_id" in flask.session:
            query = query.filter(Post.private != True)
        if same_author:
            query = query.filter(Post.author == self.author)
        return query.order_by(Post.pub_date.desc()).first()

    @werkzeug.cached_property
    def next(self):
        return self.get_previous()

    @werkzeug.cached_property
    def prev(self):
        return self.get_next()

    @werkzeug.cached_property
    def next_of_same_author(self):
        return self.get_next(True)

    @werkzeug.cached_property
    def prev_of_same_author(self):
        return self.get_previous(True)

### ReST helpers

class CodeElement(nodes.General, nodes.FixedTextElement):
    pass

class DelElement(nodes.General, nodes.TextElement):
    pass

class CodeBlock(rst.Directive):
    """
    Directive for a code block.
    """

    styles = ('linenos', )

    def style(argument):
        return rst.directives.choice(argument, CodeBlock.styles)

    has_content = True
    required_arguments = 1
    optional_arguments = 0
    option_spec = {
        'style': style
    }

    def run(self):
        code = u'\n'.join(self.content)
        node = CodeElement(code)

        style = self.options['style'].split(' ') if 'style' in self.options \
            else []
        for s in CodeBlock.styles:
            node[s] = s in style

        try:
            pygments.lexers.get_lexer_by_name(self.arguments[0])
            node['lang'] = self.arguments[0]
        except pygments.lexers.ClassNotFound:
            node['lang'] = 'text'
            error = self.state_machine.reporter.error(
                "Error in '%s' directive: no lexer with name '%s' exists." % \
                (self.name, self.arguments[0]), line=self.lineno)
            return [error, node]

        return [node]

class Math(rst.Directive):
    """
    Directive for some latex-styled math.
    """

    has_content = True
    required_arguments = 0
    optional_arguments = 0
    option_spec = {"aligned": rst.directives.flag}

    def run(self):
        if "aligned" in self.options:
            container_text = "\\begin{aligned}\n%s\n\\end{aligned}"
        else:
            container_text = r"\[%s\]"
        node = nodes.inline("", container_text % (u"\n".join(self.content), ))
        return [node]

rst.directives.register_directive('code-block', CodeBlock)
rst.directives.register_directive("math", Math)

class Translator(docutils.writers.html4css1.HTMLTranslator):
    def visit_CodeElement(self, node):
        lexer = pygments.lexers.get_lexer_by_name(node["lang"])
        formatter = pygments.formatters.get_formatter_by_name("html",
                                                              linenos=node['linenos'])
        code = pygments.highlight(node.rawsource, lexer, formatter)
        self.body.append(self.starttag(node, "div", CLASS="syntax"))
        self.body.append(code)

    def depart_CodeElement(self, node):
        self.body.append("</div>")

    def visit_DelElement(self, node):
        self.body.append(self.starttag(node, "del"))

    def depart_DelElement(self, node):
        self.body.append("</del>")

class Writer(docutils.writers.html4css1.Writer):
    def __init__(self):
        docutils.writers.html4css1.Writer.__init__(self)
        self.translator_class = Translator

def del_role(role, rawtext, text, lineno, inline, options={}, content=[]):
    node = DelElement(rawtext, text, **options)
    return [node], []

def math_role(role, rawtext, text, lineno, inliner,
                       options={}, content=[]):
    text = r"\(%s\)" % (docutils.utils.unescape(text, True), )
    node = nodes.inline(rawtext, text, **options)
    return [node], []

def post_role(role, rawtext, text, lineno, inliner, options={}, content=[]):
    try:
        idxl = text.rindex(' <')
        idxr = text.find('>', idxl + 1)
        if idxr + 1 != len(text):
            msg = inliner.reporter.error(
                "Only 'slug' and 'title <slug>' are allowed; '%s' is invalid." \
                    % (text, ), line=lineno)
            prb = inliner.problematic(rawtext, rawtext, msg)
            return [prb], [msg]

        title = text[:idxl]
        slug = text[idxl + 2:idxr]
    except ValueError:
        title = None
        slug = text

    entry = Post.query.filter_by(slug=slug).first()
    if entry is None:
        msg = inliner.reporter.error(
            "Entry with slug '%s' doesn't exist." % (slug, ), line=lineno)
        prb = inliner.problematic(rawtext, rawtext, msg)
        return [prb], [msg]

    if title is None:
        title = entry.title

    ref = flask.url_for('show_entry', slug=slug)
    node = nodes.reference(rawtext, title, refuri=ref, **options)
    return [node], []


rst.roles.register_canonical_role("del", del_role)
rst.roles.register_canonical_role("math", math_role)
rst.roles.register_canonical_role("post", post_role)

### Helpers

def get_posts(author=None, tags=None):
    query = Post.query.order_by(Post.pub_date.desc())
    if tags is not None:
        query = Post.query.join(Post.tags).filter(Tag.tag.in_(tags)) \
                .group_by(Post.id) \
                .having(func.count(Post.id) == len(tags))
    if author is not None:
        query = query.filter_by(author=author)
    if not "user_id" in flask.session:
        query = query.filter(Post.private != True) \
                .filter(Post.published == True)
    else:
        user = get_user()
        allowed_to_read = [u.id for u in user.authors]
        query = query.filter(or_(Post.user_id.in_(allowed_to_read),
                                 Post.private != True))
        if user.editor:
            query = query.filter(or_(Post.published == True,
                                     Post.author == user))
        else:
            query = query.filter(Post.published == True)
    query = query.order_by(Post.pub_date.desc())
    # XXX
    query.count = lambda _count=query.count: _count() or 0
    return query

def get_tags(string):
    """
    Given a string with comma-separated tag names, return the
    corresponding `Tag` objects. If a tag cannot be found for a given
    name, a new one will be crated and added to the database session.
    """
    tags = list()
    names = set(name.strip() for name in string.split(","))
    for name in names:
        if not name:
            continue
        tag = Tag.query.filter_by(tag=name).first()
        if tag is None:
            tag = Tag(name)
            db.session.add(tag)
        tags.append(tag)
    return tags

def get_user():
    # XXX: this should fail somehow if we have a invalid session cookie;
    # maybe redirect to an error page?
    return User.query.get(flask.session["user_id"])

def requires_login(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not "user_id" in flask.session:
            flask.flash("Sorry, you are not allowed to do that. "
                        "Please log in first.")
            flask.session["real_url"] = flask.request.url
            return flask.redirect(flask.url_for("login"))
        return func(*args, **kwargs)
    return wrapper

def requires_editor(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not flask.session["is_editor"]:
            flask.flash("Sorry, you have to be an editor to do this.")
            return flask.redirect(flask.url_for("index"))
        return func(*args, **kwargs)
    return wrapper

def slugify(value):
    value = unicodedata.normalize("NFKD", value)
    value = value.translate({0x308: u"e", ord(u"ß"): u"ss"})
    value = value.encode("ascii", "ignore").lower()
    value = re.sub(r'[^a-z0-9\s-]', '', value).strip()
    return re.sub(r'[-\s]+', '-', value)

### Template filters
def datetimeformat(value, format='%H:%M / %d-%m-%Y'):
    return value.strftime(format)

app.jinja_env.filters['datetimeformat'] = datetimeformat

app.jinja_env.globals['BLOG_TITLE'] = BLOG_TITLE
app.jinja_env.globals['BLOG_SUBTITLE'] = BLOG_SUBTITLE

### Views

@app.route("/")
def index():
    return show_entries(1)

@app.route("/<int:page>")
def show_entries(page, author=None, tags=None, template_globals=None):
    page = get_posts(author=author, tags=tags).paginate(page, 10, page != 1)
    return flask.render_template("show_entries.html", author=author, page=page,
                                 **(template_globals or dict()))

@app.route("/<author>")
def author_index(author):
    return author_show_entries(1, author=author)

@app.route("/<author>/<int:page>")
def author_show_entries(page, author=None):
    author = User.query.filter_by(name=author).first_or_404()
    return show_entries(page, author=author,
                        template_globals=dict(BLOG_TITLE=author.blog_title,
                                              BLOG_SUBTITLE=author.blog_subtitle))

@app.route("/archive")
def show_archive():
    return show_archive_page(1)

@app.route("/archive/<int:page>")
def show_archive_page(page, author=None, tags=None):
    page = get_posts(author, tags).paginate(page, 10, page != 1)
    return flask.render_template("show_archive.html", page=page, author=author)

@app.route("/<author>/archive")
def author_show_archive(author):
    author = User.query.filter_by(name=author).first_or_404()
    return show_archive_page(1, author=author)

@app.route("/<author>/archive/<int:page>")
def author_show_archive_page(author, page):
    author = User.query.filter_by(name=author).first_or_404()
    return show_archive_page(page, author=author)

@app.route("/tagged/<tags>")
def show_entries_for_tag(tags):
    return show_entries(1, tags=tags.split(","))

@app.route("/read/<slug>")
def show_entry(slug, author=None):
    entry = Post.query.filter_by(slug=slug).first_or_404()
    if entry.private:
        if not "user_id" in flask.session:
            flask.session["real_url"] = flask.request.url
            return flask.redirect(flask.url_for("login"))
        if entry.author not in get_user().authors:
            flask.abort(403)
    if author and entry.author != author:
        flask.abort(404)
    if (not entry.published and not
        ("user_id" in flask.session and entry.author == get_user())):
        flask.abort(404)
    return flask.render_template("show_entry.html", entry=entry, author=author,
                                 BLOG_TITLE=entry.author.blog_title,
                                 BLOG_SUBTITLE=entry.author.blog_subtitle)

@app.route("/<author>/read/<slug>")
def author_show_entry(author, slug):
    author = User.query.filter_by(name=author).first_or_404()
    return show_entry(slug, author)

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
    flask.session["user_name"] = user.name
    flask.session["is_editor"] = user.editor
    return flask.redirect(flask.session.pop("real_url", flask.url_for("index")))

@app.route("/logout")
def logout():
    flask.session.pop("user_id", None)
    flask.session.pop("user_name", None)
    flask.session.pop("is_editor", None)
    flask.flash("You have been logged out.")
    return flask.redirect(flask.url_for("index"))

@app.route("/add")
@requires_login
@requires_editor
def add_entry_form(text="", tags=""):
    return flask.render_template("add.html", text=text, tags=tags)

@app.route("/add", methods=["POST"])
def add_entry():
    if not "user_id" in flask.session or not flask.session["is_editor"]:
        flask.abort(403)
    form = flask.request.form
    if not form["title"]:
        flask.flash("Sorry, a title is required.")
        return add_entry_form(form["content"], form["tags"])
    summary_parts = docutils.core.publish_parts(form["summary"],
                                                writer=Writer())
    parts = docutils.core.publish_parts(form["content"], writer=Writer())
    user = User.query.get(flask.session["user_id"])
    post = Post(title=form["title"], summary=form["summary"],
                summary_html=summary_parts["body"], content=form["content"],
                html=parts["body"], author=user, private=("private" in form),
                published=("published" in form))
    post.tags = get_tags(form["tags"])
    slug = slugify(form["title"])
    counter = None
    while Post.query.filter_by(slug=slug).first():
        if counter is None:
            counter = itertools.count(2)
            slug += '-' + str(counter.next())
        else:
            slug = "%s-%i" % (slug.rsplit("-", 1)[0], counter.next())
    post.slug = slug
    db.session.add(post)
    db.session.commit()
    return flask.redirect(flask.url_for("index"))

@app.route("/edit/<slug>")
@requires_login
@requires_editor
def edit_entry_form(slug):
    entry = Post.query.filter_by(slug=slug).first_or_404()
    return flask.render_template("edit.html", entry=entry)

@app.route("/delete/<slug>")
@requires_login
@requires_editor
def delete_entry_form(slug):
    entry = Post.query.filter_by(slug=slug).first_or_404()
    return flask.render_template("confirm_delete.html", entry=entry)

@app.route("/delete", methods=["POST"])
@requires_login
def delete_entry():
    entry = Post.query.get_or_404(flask.request.form["id"])
    if entry.author.id != flask.session["user_id"]:
        flask.abort(403)
    flask.flash('Post "%s" deleted.' % (entry.title, ))
    db.session.delete(entry)
    db.session.commit()
    return flask.redirect(flask.url_for("index"))

@app.route("/save", methods=["POST"])
def save_entry():
    if not "user_id" in flask.session or not flask.session["is_editor"]:
        flask.abort(403)
    form = flask.request.form
    try:
        entry = Post.query.get_or_404(int(form["id"]))
    except ValueError:
        flask.abort(404)
    if entry.author.id != flask.session["user_id"]:
        flask.abort(403)
    if not entry.content and entry.html:
        entry.html = form["content"]
    else:
        entry.content = form["content"]
    entry.summary = form["summary"]
    entry.tags = get_tags(form["tags"])
    entry.private = "private" in form
    entry.published = "published" in form
    if not form["title"]:
        flask.flash("Sorry, but a title is required.")
        return flask.render_template("edit.html", entry=entry)
    entry.title = form["title"]
    summary_parts = docutils.core.publish_parts(form["summary"], writer=Writer())
    entry.summary_html = summary_parts["body"]
    # Check that it is no html-only entry
    if entry.content or not entry.html:
        parts = docutils.core.publish_parts(form["content"], writer=Writer())
        entry.html = parts["body"]
    db.session.commit()
    flask.flash('Post "%s" has been updated.' % (entry.title, ))
    return flask.redirect(flask.url_for("show_entry", slug=entry.slug))

@app.route("/atom")
def atom_feed(author=None):
    if "auth" in flask.request.args:
        auth = flask.request.authorization
        if auth:
            user = User.query.filter_by(name=auth.username).first()
            # The RFC does not specify which encoding is used for the
            # password. latin1 seems to be widely used, but some
            # browsers like chrome or opera send it utf-8
            # encoded. Hence, we try to decode using utf-8 with a
            # fallback to latin1.
            try:
                password = auth.password.decode("utf-8")
            except UnicodeDecodeError:
                password = auth.password.decode("latin1")
            if user is None or not user.check_password(password):
                flask.abort(403)
        else:
            return flask.Response(
                "Please authenticate.",
                401,
                {"WWW-Authenticate": 'Basic realm="Login Required"'}
            )
    if author is not None:
        title = author.blog_title
        subtitle = author.blog_subtitle
    else:
        title = BLOG_TITLE
        subtitle = BLOG_SUBTITLE
    feed = atom.AtomFeed(title, feed_url=flask.request.url,
                         url=flask.request.host_url, subtitle=subtitle)
    query = Post.query.order_by(Post.pub_date.desc()) \
            .filter(Post.published == True)
    if "auth" in flask.request.args:
        allowed_to_read = [u.id for u in user.authors]
        query = query.filter(Post.user_id.in_(allowed_to_read))
    elif not "user_id" in flask.session:
        query = query.filter(Post.private != True)
    else:
        allowed_to_read = [u.id for u in get_user().authors]
        query = query.filter(or_(Post.user_id.in_(allowed_to_read),
                                 Post.private != True))
    if author is not None:
        query = query.filter(Post.author == author)
    for post in query.limit(10):
        feed.add(post.title, post.html, content_type="html",
                 author=post.author.name,
                 url=flask.url_for("show_entry", slug=post.slug), id=post.id,
                 updated=post.pub_date, published=post.pub_date)
    return feed.get_response()

@app.route("/<author>/atom")
def author_atom_feed(author):
    author = User.query.filter_by(name=author).first_or_404()
    return atom_feed(author)

@app.route("/changepassword")
@requires_login
def change_password_form():
    return flask.render_template("change_password.html")

@app.route("/changepassword", methods=["POST"])
@requires_login
def change_password():
    user = get_user()
    form = flask.request.form
    if not form["password"]:
        flask.flash(u"A new password is required.")
    elif user.check_password(form["old_password"]):
        flask.flash(u"Password changed.")
        user.set_password(form["password"])
        db.session.commit()
        return flask.redirect(flask.url_for("index"))
    else:
        flask.flash(u"Sorry, try again.")
    return change_password_form()

@app.route("/changetitle")
@requires_login
@requires_editor
def change_title_form():
    user = get_user()
    return flask.render_template("change_title.html",title=user.blog_title,
                                 subtitle=user.blog_subtitle)

@app.route("/changetitle", methods=["POST"])
@requires_login
@requires_editor
def change_title():
    user = get_user()
    user.blog_title = flask.request.form["title"]
    user.blog_subtitle = flask.request.form["subtitle"]
    db.session.commit()
    flask.flash(u"Blog title updated.")
    return flask.redirect(flask.url_for("index"))

if __name__ == '__main__':
    import sys
    args = sys.argv[1:]
    if args:
        if args[0] == "add_user":
            user = User(args[1], args[2], editor=(len(args) == 4))
            user.authors.append(user)
            db.session.add(user)
            db.session.commit()
        elif args[0] == "init_db":
            db.create_all()
        else:
            app.run(args[0], int(args[1]))
    else:
        app.run()

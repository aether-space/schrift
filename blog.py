import datetime
import itertools
import string

import docutils.core
import docutils.writers.html4css1
from docutils import nodes
from docutils.parsers import rst
import flask
import pygments
import pygments.lexers, pygments.formatters
from flaskext import couchdb
from werkzeug.contrib import atom

DEBUG = True
COUCHDB_SERVER = "http://localhost:5984/"
COUCHDB_DATABASE = "blog"
SECRET_KEY = "XI5auBoeiH2TErtf8Hfi"

app = flask.Flask(__name__)
app.config.from_object(__name__)
manager = couchdb.CouchDBManager()

class BlogPost(couchdb.Document):
    doc_type = "blogpost"

    title = couchdb.TextField()
    content = couchdb.TextField()
    html = couchdb.TextField()
    author = couchdb.TextField()
    published = couchdb.DateTimeField(default=datetime.datetime.now)
    tags = couchdb.ListField(couchdb.TextField())

    all = couchdb.ViewField("blog", string.Template("""
        function (doc) {
            if (doc.doc_type == '$doc_type') {
                emit(doc.time, doc);
            };
        }""").substitute(**locals()), descending=True)

    tagged = couchdb.ViewField("blog", string.Template("""
    function (doc) {
        if (doc.doc_type == '$doc_type') {
            doc.tags.forEach(function (tag) {
                emit(tag, doc);
            });
        };
    }""").substitute(**locals()))

manager.add_document(BlogPost)
manager.setup(app)

# ReST helpers

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

@app.route("/")
def show_entries(tag=None):
    if tag is not None:
        posts = BlogPost.tagged[tag]
    else:
        posts = BlogPost.all()
    page = couchdb.paginate(posts, 10, flask.request.args.get('start'))
    return flask.render_template("show_entries.html", tag=tag, page=page)

@app.route("/<tag>")
def show_entries_for_tag(tag):
    return show_entries(tag)

@app.route("/show/<id>")
def show_entry(id):
    entry = BlogPost.load(id)
    return flask.render_template("show_entry.html", entry=entry)

@app.route("/add")
def add_entry_form():
    return flask.render_template("add.html")

@app.route("/add", methods=["POST"])
def add_entry():
    form = flask.request.form
    parts = docutils.core.publish_parts(form["content"], writer=Writer())
    print parts["body"], `form["content"]`
    post = BlogPost(title=form["title"], content=form["content"],
                    html=parts["body"], author="Andy")
    post.store()
    return flask.redirect(flask.url_for('show_entries'))

@app.route("/atom")
def atom_feed():
    feed = atom.AtomFeed("choblog", feed_url=flask.request.url,
                         url=flask.request.host_url,
                         subtitle="Tired musings of a chief hacking officer.")
    for post in itertools.islice(BlogPost.all(), 10):
        print post, vars(post)
        feed.add(post.title, post.html, content_type="html",
                 author=post.author,
                 url=flask.url_for("show_entry", id=post.id), id=post.id,
                 updated=post.published, published=post.published)
    return feed.get_response()

if __name__ == '__main__':
    import sys
    if sys.argv[1:]:
        app.run(sys.argv[1], int(sys.argv[2]))

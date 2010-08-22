# coding: utf-8

import unittest

import schrift

class SchriftTest(unittest.TestCase):
    def setUp(self):
        schrift.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        self.app = schrift.app.test_client()
        schrift.db.create_all()
        self.setUpUsers()

    def setUpUsers(self):
        """
        Helper function to add the test users to the database.
        """
        self.author = schrift.User("Author", "1235", editor=True)
        self.author.authors.append(self.author)
        self.author.blog_title = u"Author s blog title"
        self.reader = schrift.User("Reader", "1235")
        self.reader.authors.append(self.author)
        self.unauthorized = schrift.User("Spam", "1235")
        schrift.db.session.add(self.author)
        schrift.db.session.add(self.reader)
        schrift.db.session.add(self.unauthorized)
        schrift.db.session.commit()

    def add_post(self, title, content, summary="", private=False):
        """
        Helper function to add a new blog post.
        """
        return self.app.post("/add", follow_redirects=True,
                             data=dict(title=title, content=content,
                                       private=private,
                                       summary=summary, tags=""))

    def login(self, name):
        """
        Helper function to login.
        """
        return self.app.post("/login", follow_redirects=True,
                             data=dict(name=name, password="1235"))

    def logout(self):
        """
        Helper function to logout.
        """
        return self.app.get("/logout", follow_redirects=True)

    def test__empty_db(self):
        """
        Start with an empty database.
        """
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)

    def test_login_logout(self):
        for name in ["Author", "Reader", "Spam"]:
            response = self.login(name)
            self.assertTrue("Logged in as " + name in response.data)
            response = self.logout()
            self.assertTrue("logged out" in response.data)

    def test_change_password(self):
        self.login("Author")
        response = self.app.post("/changepassword",
                                 data=dict(old_password="", password=""))
        self.assertTrue(u"A new password is required." in response.data)
        response = self.app.post("/changepassword", follow_redirects=True,
                                 data=dict(old_password="1235", password="9876"))
        self.assertTrue(u"Password changed." in response.data)
        response = self.app.post("/changepassword",
                                 data=dict(old_password="1235", password="9876"))
        self.assertTrue(u"Sorry, try again." in response.data)
        # Change password back
        self.app.post("/changepassword",
                      data=dict(old_password="9876", password="1235"))

    def test_blog_title(self):
        # Add 11 blog posts (pagination needed)
        self.login("Author")
        for _ in xrange(11):
            self.add_post(u"blog title test", content=u"Nothing.")
        # Test itself
        for url in ["/", "/2"]:
            response = self.app.get(url)
            self.assertTrue(schrift.BLOG_TITLE in response.data)
        for url in ["/Author", "/Author/2"]:
            response = self.app.get(url)
            self.assertTrue(self.author.blog_title in response.data)

    def test_edit(self):
        self.login("Author")
        title = u"Editing test post"
        new_title = u"An edited test post"
        slug = schrift.slugify(title)
        response = self.add_post(title, content="Spam", summary=u"Old summary.")
        entry = schrift.db.session.query(schrift.Post).filter_by(slug=slug).first()
        response = self.app.post("/save", follow_redirects=True,
                                 data=dict(id=entry.id, summary=u"New summary",
                                           title=new_title, content=u"New Spam",
                                           tags=""))
        self.assertTrue(u"New Spam" in response.data)
        entry = schrift.db.session.query(schrift.Post).filter_by(slug=slug).first()
        self.assertEquals(u"New summary", entry.summary)
        self.assertEquals(new_title, entry.title)

    def test_private(self):
        self.login("Author")
        title = u"Post with a title"
        content = u"This is the post's content (test_private)."
        read_url = "/read/" + schrift.slugify(title)
        response = self.add_post(title, content, private=True)
        self.assertTrue(content in response.data)
        self.logout()
        # Only logged in users can read it
        response = self.app.get("/")
        self.assertFalse(content in response.data)
        response = self.app.get(read_url)
        self.assertEquals(response.status_code, 302)
        self.assertTrue(u"Redirecting" in response.data)
        response = self.app.get("/atom")
        self.assertFalse(content in response.data)
        # Reader is allowed to read it
        self.login("Reader")
        response = self.app.get("/")
        self.assertTrue(content in response.data)
        response = self.app.get(read_url)
        self.assertTrue(content in response.data)
        response = self.app.get("/atom")
        self.assertTrue(content in response.data)
        self.logout()
        # Spam isn't allowed to read it
        self.login("Spam")
        response = self.app.get("/")
        self.assertFalse(content in response.data)
        response = self.app.get(read_url)
        self.assertEquals(response.status_code, 403)
        response = self.app.get("/atom")
        self.assertFalse(content in response.data)
        self.logout()

    def test_duplicates(self):
        title = u"Duplicated title"
        read_url = "/read/" + schrift.slugify(title)
        self.login("Author")
        self.add_post(title, u"Spam")
        self.add_post(title, u"Spam")
        response = self.add_post(title, u"Spam")
        self.assertTrue(read_url in response.data)
        self.assertTrue(read_url + "-2" in response.data)
        self.assertTrue(read_url + "-3" in response.data)

    def test_user(self):
        self.login("Author")
        title = u"A public post."
        content = u"This is a public post (test_user)."
        read_url = "/Author/read/" + schrift.slugify(title)
        response = self.add_post(title, content)
        self.assertTrue(content in response.data)
        response = self.app.get(read_url)
        self.assertTrue(content in response.data)

    def test_slugify(self):
        self.assertEqual(schrift.slugify(u"ßpäm"), u"sspaem")
        self.assertEqual(schrift.slugify(u"slug With spaces"),
                         u"slug-with-spaces")
        self.assertEqual(schrift.slugify(u"foo@bar"), u"foobar")
        self.assertEqual(schrift.slugify(u"slug  with multiple -- spaces"),
                                         u"slug-with-multiple-spaces")
        self.assertEqual(schrift.slugify(u"42"), u"42")

if __name__ == "__main__":
    unittest.main()

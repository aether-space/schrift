# coding: utf-8

import unittest

import schrift

class SchriftTest(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(schrift.slugify(u"ßpäm"), u"sspaem")
        self.assertEqual(schrift.slugify(u"slug With spaces"),
                         u"slug-with-spaces")

if __name__ == "__main__":
    unittest.main()

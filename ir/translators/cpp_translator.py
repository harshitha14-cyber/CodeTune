from .c_translator import CTranslator


class CppTranslator(CTranslator):
    """
    C++'s grammar is a superset of C's, and for the deliberately small
    subset CodeTune supports (typed functions, variable declarations,
    arithmetic/logical expressions, if/while/for, return, calls) the two
    grammars produce the same node shapes. `_condition_expr` in the base
    class already strips whichever wrapper node C++ uses around an if/while
    condition, so no override is needed there.

    C++-only syntax (templates, classes, references, `auto`, ...) is rejected
    by the shared translator with a clear message rather than mistranslated.
    """
    source_language = "cpp"
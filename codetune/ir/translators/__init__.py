from .python_translator import PythonTranslator
from .c_translator import CTranslator
from .cpp_translator import CppTranslator
from .java_translator import JavaTranslator

TRANSLATORS = {
    "python": PythonTranslator,
    "c": CTranslator,
    "cpp": CppTranslator,
    "java": JavaTranslator,
}


def get_translator(language: str, source_bytes: bytes):
    if language not in TRANSLATORS:
        raise ValueError(f"No translator registered for language '{language}'")
    return TRANSLATORS[language](source_bytes)

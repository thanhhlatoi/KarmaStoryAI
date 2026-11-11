"""Đọc số đếm bằng chữ, không cần thư viện ngoài."""
import re

SMALL = {
    "en": "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    "de": "null eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf dreizehn vierzehn fünfzehn sechzehn siebzehn achtzehn neunzehn".split(),
    "es": "cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciséis diecisiete dieciocho diecinueve veinte veintiuno veintidós veintitrés veinticuatro veinticinco veintiséis veintisiete veintiocho veintinueve".split(),
}
TENS = {
    "en": "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split(),
    "de": "null zehn zwanzig dreißig vierzig fünfzig sechzig siebzig achtzig neunzig".split(),
    "es": "cero diez veinte treinta cuarenta cincuenta sesenta setenta ochenta noventa".split(),
}


def integer_words(number, lang):
    if number < 0:
        return {"en": "minus ", "de": "minus ", "es": "menos "}[lang] + integer_words(-number, lang)
    if number < len(SMALL[lang]):
        return SMALL[lang][number]
    if number < 100:
        tens, unit = divmod(number, 10)
        if not unit:
            return TENS[lang][tens]
        if lang == "de":
            return ("ein" if unit == 1 else SMALL[lang][unit]) + "und" + TENS[lang][tens]
        return TENS[lang][tens] + (" y " if lang == "es" else "-") + SMALL[lang][unit]
    if number < 1000:
        hundreds, remainder = divmod(number, 100)
        if lang == "en":
            prefix = SMALL[lang][hundreds] + " hundred"
        elif lang == "de":
            prefix = ("ein" if hundreds == 1 else SMALL[lang][hundreds]) + "hundert"
        else:
            prefix = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos", "ochocientos", "novecientos"][hundreds]
            if number == 100:
                return "cien"
        return prefix + (("" if lang == "de" else " ") + integer_words(remainder, lang) if remainder else "")
    scales = {"en": ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand")),
              "de": ((10**12, "Billion"), (10**9, "Milliarde"), (10**6, "Million"), (1000, "tausend")),
              "es": ((10**12, "billón"), (10**9, "mil millones"), (10**6, "millón"), (1000, "mil"))}
    if number >= 10**15:
        return " ".join(SMALL[lang][int(digit)] for digit in str(number))
    for size, label in scales[lang]:
        if number < size:
            continue
        count, remainder = divmod(number, size)
        prefix = integer_words(count, lang)
        if lang == "de":
            if size == 1000:
                prefix = ("ein" if count == 1 else prefix) + label
            else:
                prefix = ("eine" if count == 1 else prefix) + " " + label + ("n" if size == 10**9 and count != 1 else "en" if count != 1 else "")
        elif lang == "es":
            if size == 1000:
                prefix = "mil" if count == 1 else _apocopate(prefix) + " mil"
            elif size == 10**9:
                prefix = "mil millones" if count == 1 else _apocopate(prefix) + " mil millones"
            else:
                prefix = "un " + label if count == 1 else _apocopate(prefix) + " " + ("millones" if size == 10**6 else "billones")
        else:
            prefix += " " + label
        separator = "" if lang == "de" and size == 1000 else " "
        return prefix + (separator + integer_words(remainder, lang) if remainder else "")


def _apocopate(text):
    if text.endswith("veintiuno"):
        return text[:-9] + "veintiún"
    if text.endswith("uno"):
        return text[:-3] + "un"
    return text


def expand_numbers(text, lang):
    decimal = "." if lang == "en" else ","
    grouping = "," if lang == "en" else "."

    def replace(match):
        token = match[0].replace(grouping, "")
        whole, separator, fraction = token.partition(decimal)
        result = integer_words(int(whole), lang)
        if separator:
            result += {"en": " point ", "de": " Komma ", "es": " coma "}[lang]
            result += " ".join(SMALL[lang][int(digit)] for digit in fraction)
        return result

    pattern = rf"(?<!\w)-?\d+(?:{re.escape(grouping)}\d{{3}})*(?:{re.escape(decimal)}\d+)?(?!\w)"
    text = re.sub(pattern, replace, text)
    # Chữ số kề đơn vị (60+, 2km, mã số...) vẫn không được lọt vào TTS.
    text = re.sub(r"\d+", lambda m: integer_words(int(m[0]), lang), text)
    return text.replace("%", {"en": " percent", "de": " Prozent", "es": " por ciento"}[lang])

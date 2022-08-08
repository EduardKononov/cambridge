"""Script to parse and print cambridge dictionary."""

import sys
import requests
import threading
import sqlite3

from cambridge.console import console
from cambridge.errors import ParsedNoneError, call_on_error
from cambridge.settings import OP, DICTS
from cambridge.log import logger
from cambridge.cache import insert_into_table, get_cache
from cambridge.utils import make_a_soup, get_request_url, get_request_url_spellcheck, parse_response_url, replace_all
from cambridge.fetch import fetch


CAMBRIDGE_DICT_BASE_URL = "https://dictionary.cambridge.org/dictionary/english/"  # if no result found in cambridge, response.url is this.
CAMBRIDGE_SPELLCHECK_URL = "https://dictionary.cambridge.org/spellcheck/english/?q="


# ----------Request Web Resouce----------
def search_cambridge(con, cur, input_word):
    request_url = get_request_url(CAMBRIDGE_DICT_BASE_URL, input_word, DICTS[0])
    data = get_cache(con, cur, input_word, request_url)  # data is a tuple if any

    if data is not None:    
        logger.debug(f'{OP[5]} "{input_word}" cached before. Use cache')
        response_url = data[0]
        soup = make_a_soup(data[1])
        parse_and_print(response_url, soup)

    else:
        result = fetch_cambridge(request_url, input_word)
        found = result[0]

        if found:
            response_url, response_text = result[1]
            soup = make_a_soup(response_text) 
            response_word = parse_response_word(soup)

            parse_thread = threading.Thread(
                target=parse_and_print, args=(response_url, soup)
            )
            parse_thread.start()

            save(con, cur, input_word, response_word, response_url, response_text)

        else:
            spellcheck_response_url, spellcheck_response_text = result[1]
            soup = make_a_soup(spellcheck_response_text)
            parse_and_print(spellcheck_response_url, soup)


def fetch_cambridge(request_url, input_word):
    with requests.Session() as session:
        session.trust_env = False
        response = fetch(request_url, session)

        if response.url == CAMBRIDGE_DICT_BASE_URL:
            logger.debug(f'{OP[6]} "{input_word}" in Cambridge')

            spellcheck_request_url = get_request_url_spellcheck(CAMBRIDGE_SPELLCHECK_URL, input_word)
            spellcheck_response = fetch(spellcheck_request_url, session)
            spellcheck_response_url = spellcheck_response.url
            spellcheck_response_text = spellcheck_response.text

            return False, (spellcheck_response_url, spellcheck_response_text)
        else:
            response_url = parse_response_url(response.url)
            response_text = response.text

            logger.debug(f'{OP[5]} "{input_word}" in Cambridge at {response_url}')
            return True, (response_url, response_text)


# ----------Cache Web Resource----------
def save(con, cur, input_word, response_word, response_url, response_text):
    try:
        insert_into_table(
            con, cur, input_word, response_word, response_url, response_text
        )
        logger.debug(f'{OP[7]} the search result of "{input_word}"')
    except sqlite3.IntegrityError as e:
        logger.debug(f'{OP[8]} caching "{input_word}" because of {str(e)}')
        pass


# ----------The Entry Point For Parse And Print----------
def parse_and_print(url, soup):
    """The entry point of this module to parse the dict and print the info about the word."""

    logger.debug(f"{OP[1]} the fetched result of {url}")

    if "spellcheck" in url :
        logger.debug(f"{OP[4]} the parsed result of {url}")
        parse_spellcheck(soup)
        sys.exit()

    blocks, first_dict = parse_dict_blocks(url, soup)

    logger.debug(f"{OP[4]} the parsed result of {url}")
    for block in blocks:
        parse_dict_head(block)
        parse_dict_body(block)
    parse_dict_name(first_dict)


def parse_dict_blocks(url, soup):
    """Parse different form sections for the word."""

    first_dict = parse_first_dict(url, soup)

    attempt = 0
    while True:
        try:
            result = first_dict.find(
                "div", ["pr entry-body__el", "entry-body__el clrd js-share-holder"]
            )
        except AttributeError as e:
            attempt = call_on_error(e, url, attempt, OP[3])

        if result:
            blocks = first_dict.find_all(
                "div", ["pr entry-body__el", "entry-body__el clrd js-share-holder"]
            )
        else:
            blocks = first_dict.find_all("div", "pr idiom-block")

        return blocks, first_dict


def parse_first_dict(url, soup):
    """Parse the dict section of the page for the word."""

    attempt = 0
    while True:
        try:
            first_dict = soup.find("div", "pr dictionary")
        except Exception as e:
            attempt = call_on_error(e, url, attempt, OP[3])

        if first_dict is None:
            attempt = call_on_error(ParsedNoneError(), url, attempt, OP[3])

        return first_dict


# ----------Parse Spellcheck----------
def parse_spellcheck(soup):
    """Parse Cambridge spellcheck page and print it to the terminal."""

    content = soup.find("div", "hfl-s lt2b lmt-10 lmb-25 lp-s_r-20")

    title = content.h1.text.split("for")[1].strip()
    console.print("\n[bold]" +  title)

    for ul in content.find_all("ul", "hul-u"):
        notice = ul.find_previous_sibling().text
        console.print("[bold #3C8DAD]" + "\n" + notice)
        for i in ul.find_all("li"):
            suggestion = replace_all(i.text)
            console.print("[#b2b2b2]" + "  • " + suggestion)


# ----------Parse Response Word----------
def parse_response_word(soup):
    "Parse the response word from html title tag."

    response_word = soup.find("title").text.split("|")[0].strip().lower()
    return response_word


# ----------Parse Dict Head----------
# Compared to Webster Dictionary, Cambridge is a bunch of deep layered html tags filled with unbearably messy class names.
# No clear pattern, somewhat irregular, sometimes you just need to tweak your codes for particular words and phrases for them to show. 

def parse_head_title(block):
    word = block.find("div", "di-title").text
    return word


def parse_head_info(block):
    info = block.find("span", "di-info")
    return info 


def parse_head_type(head):
    if head.find("span", "anc-info-head danc-info-head"):
        w_type = (
            head.find("span", "anc-info-head danc-info-head").text
            + head.find(
                "span",
                attrs={
                    "title": "A word that describes an action, condition or experience."
                },
            ).text
        )
        w_type = replace_all(w_type)
    elif head.find("div", "posgram dpos-g hdib lmr-5"):
        posgram = head.find("div", "posgram dpos-g hdib lmr-5")
        w_type = replace_all(posgram.text)
    else:
        w_type = "" 
    return w_type


def parse_head_pron(head):
    w_pron_uk = head.find("span", "uk dpron-i").find("span", "pron dpron")
    if w_pron_uk:
        w_pron_uk = replace_all(w_pron_uk.text)
    # In bs4, not found element returns None, not raise error, so try block is not right
    w_pron_us = head.find("span", "us dpron-i").find("span", "pron dpron")
    if w_pron_us:
        w_pron_us = replace_all(w_pron_us.text)
        console.print(
            "[bold]UK [/bold]" + w_pron_uk + "[bold] US [/bold]" + w_pron_us, end="  "
        )
    else:
        console.print("[bold]UK [/bold]" + w_pron_uk, end="  ")


def parse_head_tense(head):
    w_tense = replace_all(head.find("span", "irreg-infls dinfls").text)
    console.print("[bold]" + w_tense, end="  ")


def parse_head_domain(head):
    domain = replace_all(head.find("span", "domain ddomain").text)
    console.print("[bold]" + domain, end="  ")


def parse_head_usage(head):
    if head.find("span", "lab dlab"):
        w_usage = replace_all(head.find("span", "lab dlab").text)
        console.print("[bold]" + w_usage, end="  ")
    if head.find_next_sibling("span", "lab dlab"):
        w_usage = replace_all(head.find_next_sibling("span", "lab dlab").text)
        console.print("[bold]" + w_usage, end="  ")


def parse_head_var(head):
    if head.find("span", "var dvar"):
        w_var = replace_all(head.find("span", "var dvar").text)
        console.print("[bold]" + w_var, end="  ")
    if head.find_next_sibling("span", "var dvar"):
        w_var = replace_all(head.find_next_sibling("span", "var dvar").text)
        console.print("[bold]" + w_var, end="  ")


def parse_head_spellvar(head):
    for i in head.find_all("span", "spellvar dspellvar"):
        spell_var = replace_all(i.text)
        console.print("[bold]" + spell_var, end="  ")


def parse_dict_head(block):
    head = block.find("div", "pos-header dpos-h")
    word = parse_head_title(block)
    info = parse_head_info(block)

    if head:
        head = block.find("div", "pos-header dpos-h")
        w_type = parse_head_type(head)
        if not word:
            word = parse_head_title(head)
        if w_type:
            console.print("[bold #3C8DAD on #DDDDDD]" + word + " " + w_type)
        if head.find("span", "uk dpron-i"):
            if head.find("span", "uk dpron-i").find("span", "pron dpron"):
                parse_head_pron(head)

        if head.find("span", "irreg-infls dinfls"):
            parse_head_tense(head)

        if head.find("span", "domain ddomain"):
            parse_head_domain(head)

        parse_head_usage(head)
        parse_head_var(head)

        if head.find("span", "spellvar dspellvar"):
            parse_head_spellvar(head)

        print()
        print()
    else:
        console.print("[bold #3C8DAD on #DDDDDD]" + word)
        if info:
            console.print("[#b2b2b2]" + info.text)


# ----------Parse Dict Body----------
def parse_def_title(block):
    d_title = replace_all(block.find("h3", "dsense_h").text)
    console.print("[bold #3C8DAD]" + "\n" + d_title)


def parse_ptitle(block):
    p_title = block.find("span", "phrase-title dphrase-title").text
    if block.find("span", "phrase-info dphrase-info"):
        phrase_info = "  - " + replace_all(
            block.find("span", "phrase-info dphrase-info").text
        )
        print(f"\n\033[1m  {p_title} {phrase_info}\033[0m")
    else:
        print(f"\n\033[1m  {p_title}\033[0m")


def parse_def_info(def_block):
    def_info = replace_all(def_block.find("span", "def-info ddef-info").text)
    if def_info == " ":
        def_into = ""
    if def_info:
        if "phrase-body" in def_block.parent.attrs["class"]:
            print("  " + "\033[1m" + def_info + " " + "\033[0m", end="")
        else:
            print(def_info + " ", end="")


def parse_meaning(def_block):
    meaning_b = def_block.find("div", "def ddef_d db")
    if meaning_b.find("span", "lab dlab"):
        usage_b = meaning_b.find("span", "lab dlab")
        usage = replace_all(usage_b.text)
        meaning_words = replace_all(meaning_b.text).split(usage)[-1]
        print(usage + "\033[33m" + meaning_words + "\033[0m")
    else:
        meaning_words = replace_all(meaning_b.text)
        print("\033[33m" + meaning_words + "\033[0m")


def parse_pmeaning(def_block):
    meaning_b = def_block.find("div", "def ddef_d db")
    if meaning_b.find("span", "lab dlab"):
        usage_b = meaning_b.find("span", "lab dlab")
        usage = replace_all(usage_b.text)
        meaning_words = replace_all(meaning_b.text).split(usage)[-1]
        print("  " + usage + "\033[33m" + meaning_words + "\033[0m")
    else:
        meaning_words = replace_all(meaning_b.text)
        print("  " + "\033[33m" + meaning_words + "\033[0m")


def parse_example(def_block):
    # NOTE:
    # suppose the first "if" has already run
    # and, the second is also "if", rather than "elif"
    # then, codes under "else" will also be run
    # meaning two cases took effect at the same time, which is not wanted
    # so, for exclusive cases, you can't write two "ifs" and one "else"
    # it should be one "if", one "elif", and one "else"
    # or three "ifs"
    for e in def_block.find_all("div", "examp dexamp"):
        if e is not None:
            example = replace_all(e.find("span", "eg deg").text)
            if e.find("span", "lab dlab"):
                lab = replace_all(e.find("span", "lab dlab").text)
                console.print(
                    "[#b2b2b2]"
                    + "  • "
                    + "[/#b2b2b2]"
                    + lab
                    + " "
                    + "[#b2b2b2]"
                    + example
                )
            elif e.find("span", "gram dgram"):
                gram = replace_all(e.find("span", "gram dgram").text)
                console.print(
                    "[#b2b2b2]"
                    + "  • "
                    + "[/#b2b2b2]"
                    + gram
                    + " "
                    + "[#b2b2b2]"
                    + example
                )
            elif e.find("span", "lu dlu"):
                lu = replace_all(e.find("span", "lu dlu").text)
                console.print(
                    "[#b2b2b2]"
                    + "  • "
                    + "[/#b2b2b2]"
                    + lu
                    + " "
                    + "[#b2b2b2]"
                    + example
                )
            else:
                console.print("[#b2b2b2]" + "  • " + example)


def parse_synonym(def_block):
    if def_block.find("div", "xref synonym hax dxref-w lmt-25"):
        s_block = def_block.find("div", "xref synonym hax dxref-w lmt-25")
    if def_block.find("div", "xref synonyms hax dxref-w lmt-25"):
        s_block = def_block.find("div", "xref synonyms hax dxref-w lmt-25")
    s_title = s_block.strong.text.upper()
    console.print("[bold #b2b2b2]" + "\n  " + s_title)
    for s in s_block.find_all(
        "div", ["item lc lc1 lpb-10 lpr-10", "item lc lc1 lc-xs6-12 lpb-10 lpr-10"]
    ):
        s = s.text
        console.print("[#b2b2b2]" + "  • " + s)


def parse_see_also(def_block):
    if def_block.find("div", "xref see_also hax dxref-w"):
        see_also_block = def_block.find("div", "xref see_also hax dxref-w")
    if def_block.find("div", "xref see_also hax dxref-w lmt-25"):
        see_also_block = def_block.find("div", "xref see_also hax dxref-w lmt-25")
    see_also = see_also_block.strong.text.upper()
    console.print("[bold #b2b2b2]" + "\n  " + see_also)
    for word in see_also_block.find_all("div", "item lc lc1 lpb-10 lpr-10"):
        word = word.text
        console.print("[#b2b2b2]" + "  • " + word)


def parse_compare(def_block):
    if def_block.find("div", "xref compare hax dxref-w lmt-25"):
        compare_block = def_block.find("div", "xref compare hax dxref-w lmt-25")
    if def_block.find("div", "xref compare hax dxref-w"):
        compare_block = def_block.find("div", "xref compare hax dxref-w")
    compare = compare_block.strong.text.upper()
    console.print("[bold #b2b2b2]" + "\n  " + compare)
    for word in compare_block.find_all(
        "div", ["item lc lc1 lpb-10 lpr-10", "item lc lc1 lc-xs6-12 lpb-10 lpr-10"]
    ):
        item = word.a.text
        usage = word.find("span", "x-lab dx-lab")
        if usage:
            usage = usage.text
            console.print("[#b2b2b2]" + "  • " + item + "[/#b2b2b2]" + usage)
        else:
            console.print("[#b2b2b2]" + "  • " + item)


def parse_usage_note(def_block):
    usage_block = def_block.find("div", "usagenote dusagenote daccord")
    usagenote = usage_block.h5.text
    console.print("[bold #b2b2b2]" + "\n  " + usagenote)
    for item in usage_block.find_all("li", "text"):
        item = item.text
        console.print("[#b2b2b2]" + "    " + item)


def parse_def(def_block):
    parse_def_info(def_block)
    if "phrase-body" in def_block.parent.attrs["class"]:
        parse_pmeaning(def_block)
    else:
        parse_meaning(def_block)
    parse_example(def_block)

    if def_block.find(
        "div", ["xref synonym hax dxref-w lmt-25", "xref synonyms hax dxref-w lmt-25"]
    ):
        parse_synonym(def_block)
    if def_block.find(
        "div", ["xref see_also hax dxref-w", "xref see_also hax dxref-w lmt-25"]
    ):
        parse_see_also(def_block)
    if def_block.find(
        "div", ["xref compare hax dxref-w lmt-25", "xref compare hax dxref-w"]
    ):
        parse_compare(def_block)
    if def_block.find("div", "usagenote dusagenote daccord"):
        parse_usage_note(def_block)


def parse_idiom(block):
    if block.find("div", "xref idiom hax dxref-w lmt-25 lmb-25"):
        idiom_block = block.find("div", "xref idiom hax dxref-w lmt-25 lmb-25")
    if block.find("div", "xref idioms hax dxref-w lmt-25 lmb-25"):
        idiom_block = block.find("div", "xref idioms hax dxref-w lmt-25 lmb-25")
    idiom_title = idiom_block.h3.text.upper()
    console.print("[bold #b2b2b2]" + "\n" + idiom_title)
    for idiom in idiom_block.find_all(
        "div",
        [
            "item lc lc1 lpb-10 lpr-10",
            "item lc lc1 lc-xs6-12 lpb-10 lpr-10",
        ],
    ):
        idiom = idiom.text
        console.print("[#b2b2b2]" + "  • " + idiom)


def parse_phrasal_verb(block):
    if block.find("div", "xref phrasal_verbs hax dxref-w lmt-25 lmb-25"):
        pv_block = block.find("div", "xref phrasal_verbs hax dxref-w lmt-25 lmb-25")
    if block.find("div", "xref phrasal_verb hax dxref-w lmt-25 lmb-25"):
        pv_block = block.find("div", "xref phrasal_verb hax dxref-w lmt-25 lmb-25")
    pv_title = pv_block.h3.text.upper()
    console.print("[bold #b2b2b2]" + "\n" + pv_title)
    for pv in pv_block.find_all(
        "div",
        ["item lc lc1 lc-xs6-12 lpb-10 lpr-10", "item lc lc1 lpb-10 lpr-10"],
    ):
        pv = pv.text
        console.print("[#b2b2b2]" + "  • " + pv)


def parse_dict_body(block):
    for subblock in block.find_all("div", ["pr dsense", "pr dsense dsense-noh"]):
        if subblock.find("h3", "dsense_h"):
            parse_def_title(subblock)

        for child in subblock.find("div", "sense-body dsense_b").children:
            try:
                if child.attrs["class"] == ["def-block", "ddef_block"]:
                    parse_def(child)

                if child.attrs["class"] == [
                    "pr",
                    "phrase-block",
                    "dphrase-block",
                    "lmb-25",
                ] or child.attrs["class"] == ["pr", "phrase-block", "dphrase-block"]:
                    parse_ptitle(child)

                    for i in child.find_all("div", "def-block ddef_block"):
                        parse_def(i)
            except:
                pass

    if block.find(
        "div",
        [
            "xref idiom hax dxref-w lmt-25 lmb-25",
            "xref idioms hax dxref-w lmt-25 lmb-25",
        ],
    ):
        parse_idiom(block)

    if block.find(
        "div",
        [
            "xref phrasal_verbs hax dxref-w lmt-25 lmb-25",
            "xref phrasal_verb hax dxref-w lmt-25 lmb-25",
        ],
    ):
        parse_phrasal_verb(block)


# ----------Parse Dict Name----------
def parse_dict_name(first_dict):
    dict_info = replace_all(first_dict.small.text).replace("(", "").replace(")", "")
    dict_name = dict_info.split("©")[0]
    dict_name = dict_name.split("the")[-1]
    console.print(dict_name + "\n", justify="right")

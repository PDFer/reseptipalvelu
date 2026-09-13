from flask import Flask, jsonify, render_template_string
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import os
import urllib3

load_dotenv()

app = Flask(__name__)

GROCY_URL = "https://grocy.home"
GROCY_API_KEY = os.environ["GROCY_API_KEY"]

headers = {
    "GROCY-API-KEY": GROCY_API_KEY
}

# Grocyn paikallisen mkcert-sertifikaatin tarkistusta ei tässä vielä tehdä.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def grocy_get(endpoint):
    response = requests.get(
        f"{GROCY_URL}/api/{endpoint}",
        headers=headers,
        verify=False
    )
    response.raise_for_status()
    return response.json()

def get_recipe(recipe_id, servings=None):

    # Resepti
    recipe = grocy_get(
        f"objects/recipes/{recipe_id}"
    )

    # Skaalauskerroin aterian annosmäärälle
    original_servings = recipe["desired_servings"]

    if servings is not None and original_servings:
        scale = servings / original_servings
    else:
        scale = 1

    # Raaka-aineet
    all_ingredients = grocy_get(
        "objects/recipes_pos_resolved"
    )

    ingredients_raw = [
        item for item in all_ingredients
        if item["recipe_type"] == "normal"
        and item["child_recipe_id"] == recipe_id
    ]

    # Yksiköt
    quantity_units = grocy_get(
        "objects/quantity_units"
    )

    units = {
        unit["id"]: unit["name"]
        for unit in quantity_units
    }

    # Muodostetaan raaka-aineet
    ingredients = []

    for item in ingredients_raw:

        unit = units.get(
            item["qu_id"],
            "?"
        )

        amount = item["recipe_amount"] * scale
        missing = item["missing_amount"] * scale

        if item["recipe_variable_amount"]:
            display_amount = item["recipe_variable_amount"]
        else:
            display_amount = f"{amount:g} {unit}"

        ingredients.append({
            "product": item["product_name"],
            "amount": amount,
            "unit": unit,
            "display_amount": display_amount,
            "missing": missing
        })

    # Reseptin HTML
    soup = BeautifulSoup(
        recipe["description"],
        "html.parser"
    )

    # Työvaiheet
    steps = []

    for li in soup.select("ol li"):

        text = li.get_text(
            " ",
            strip=True
        )

        if text:
            steps.append(text)

    # Muut tekstit
    notes = []

    for element in soup.find_all("p"):

        text = element.get_text(
            " ",
            strip=True
        )

        if text:
            notes.append(text)

    return {
        "id": recipe["id"],
        "name": recipe["name"],
        "servings": servings if servings is not None else recipe["desired_servings"],
        "ingredients": ingredients,
        "steps": steps,
        "notes": notes
    }

from datetime import datetime

def get_next_meal():
    meal_plan = grocy_get("objects/meal_plan")
    sections = grocy_get("objects/meal_plan_sections")

    sections_by_id = {
        section["id"]: section
        for section in sections
    }

    now = datetime.now()
    today = now.date().isoformat()
    current_time = now.strftime("%H:%M")

    # Tänään vielä tulevat ateriat
    candidates = []

    for meal in meal_plan:
        if meal["day"] < today:
            continue

        section = sections_by_id.get(meal["section_id"])

        if not section or not section.get("time_info"):
            continue

        if meal["day"] == today and section["time_info"] <= current_time:
            continue

        candidates.append((meal["day"], section["time_info"], meal))

    if not candidates:
        return None

    # Seuraava ateria ajan ja päivän perusteella
    candidates.sort(key=lambda item: (item[0], item[1]))

    day, time, first_meal = candidates[0]

    # Kerätään kaikki saman päivän + sectionin reseptit
    matching = [
        meal for meal in meal_plan
        if meal["day"] == day
        and meal["section_id"] == first_meal["section_id"]
        and meal["type"] == "recipe"
    ]

    recipes = []

    for meal in matching:
        recipe = get_recipe(
            meal["recipe_id"],
            servings=meal["recipe_servings"]
        )

        recipes.append({
            "id": recipe["id"],
            "name": recipe["name"],
            "servings": meal["recipe_servings"],
            "ingredients": recipe["ingredients"]
        })

    section = sections_by_id[first_meal["section_id"]]

    return {
        "day": day,
        "section": {
            "id": section["id"],
            "name": section["name"],
            "time": section["time_info"]
        },
        "recipes": recipes
    }


# ---------------------------------------------------------
# API
# ---------------------------------------------------------

@app.route("/api/recipe/<int:recipe_id>")
def recipe_api(recipe_id):

    try:
        result = get_recipe(recipe_id)
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


# ---------------------------------------------------------
# RECIPE PAGE
# ---------------------------------------------------------

@app.route("/recipe/<int:recipe_id>")
def recipe_page(recipe_id):

    try:
        result = get_recipe(recipe_id)

    except Exception as e:
        return f"""
        <h1>Virhe</h1>
        <p>{e}</p>
        """, 500

    return render_template_string(
        HTML,
        recipe=result
    )


# ---------------------------------------------------------
# INDEX
# ---------------------------------------------------------

RECIPE_TEMPLATE = """
<!DOCTYPE html>
<html lang="fi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ recipe.name }}</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 12px;
    background: #f4f4f4;
    color: #222;
    font-family: system-ui, sans-serif;
}

.container {
    max-width: 750px;
    margin: auto;
}

.header {
    margin-bottom: 12px;
}

h1 {
    margin: 0;
    font-size: 28px;
}

.servings {
    color: #666;
    margin-top: 4px;
}

.card {
    background: white;
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 12px;
    box-shadow: 0 2px 7px rgba(0,0,0,0.08);
}

/* Raaka-aineet */

.ingredients-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: pointer;
    user-select: none;
}

.ingredients-header h2 {
    margin: 0;
}

.arrow {
    font-size: 24px;
    transition: transform 0.2s;
}

.arrow.open {
    transform: rotate(180deg);
}

#ingredientsContent {
    margin-top: 12px;
}

.ingredient {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 4px;
    border-bottom: 1px solid #eee;
    cursor: pointer;
    font-size: 17px;
}

.ingredient:last-child {
    border-bottom: none;
}

.ingredient input {
    width: 24px;
    height: 24px;
    flex-shrink: 0;
}

.ingredient.checked {
    color: #999;
    text-decoration: line-through;
}

/* Painikkeet */

button {
    width: 100%;
    min-height: 52px;
    padding: 12px 16px;
    border: none;
    border-radius: 10px;
    background: #444;
    color: white;
    font-size: 18px;
    cursor: pointer;
}

button:active {
    transform: scale(0.98);
}

.start {
    margin-top: 14px;
}

/* Työvaiheet */

#steps {
    display: none;
}

.progress-info {
    display: flex;
    justify-content: space-between;
    color: #666;
    margin-bottom: 8px;
}

.progress {
    height: 8px;
    background: #ddd;
    border-radius: 5px;
    overflow: hidden;
    margin-bottom: 16px;
}

.progress-bar {
    height: 100%;
    width: 0%;
    background: #555;
    transition: width 0.25s;
}

.step-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.step {
    padding: 15px;
    border-radius: 10px;
    background: #eee;
    cursor: pointer;
    line-height: 1.45;
    font-size: 16px;
}

.step.active {
    background: white;
    border: 2px solid #555;
    padding: 13px;
    font-size: 19px;
    box-shadow: 0 2px 7px rgba(0,0,0,0.12);
}

.step.done {
    color: #999;
    background: #ddd;
    text-decoration: line-through;
}

.step-number {
    font-weight: bold;
    margin-right: 6px;
}

/* Valmis */

.finished {
    display: none;
    text-align: center;
    padding: 30px 10px;
}

.finished-icon {
    font-size: 52px;
}

.finished-title {
    font-size: 28px;
    font-weight: bold;
    margin: 10px 0 20px;
}

.reset {
    background: #666;
}

/* Pieni näyttö */

@media (max-width: 500px) {
    body {
        padding: 8px;
    }

    h1 {
        font-size: 24px;
    }

    .card {
        padding: 13px;
    }

    .step.active {
        font-size: 18px;
    }
}
</style>
</head>

<body>

<div class="container">

    <div class="header">
        <h1>{{ recipe.name }}</h1>
        <div class="servings">{{ recipe.servings }} annosta</div>
    </div>


    <!-- RAAKA-AINEET -->

    <div class="card" id="ingredientsCard">

        <div class="ingredients-header" onclick="toggleIngredients()">
            <h2>Raaka-aineet</h2>
            <span class="arrow" id="ingredientsArrow">▼</span>
        </div>

        <div id="ingredientsContent">

            {% for ingredient in recipe.ingredients %}

            <label class="ingredient">

                <input
                    type="checkbox"
                    data-ingredient="{{ loop.index0 }}"
                    onchange="saveIngredients()"
                >

                <span>
                    <strong>{{ ingredient.display_amount }}</strong>
                    {{ ingredient.product }}

                    {% if ingredient.missing > 0 %}
                        <small style="color:#c00">
                            (puuttuu {{ ingredient.missing }})
                        </small>
                    {% endif %}
                </span>

            </label>

            {% endfor %}

            <button class="start" onclick="startCooking()">
                Aloita valmistus
            </button>

        </div>

    </div>


    <!-- TYÖVAIHEET -->

    <div class="card" id="steps">

        <div class="progress-info">
            <span>Valmistus</span>
            <span id="progressText">Vaihe 1 / {{ recipe.steps|length }}</span>
        </div>

        <div class="progress">
            <div class="progress-bar" id="progressBar"></div>
        </div>

        <div class="step-list" id="stepList">

            {% for step in recipe.steps %}

            <div
                class="step"
                data-step="{{ loop.index0 }}"
                onclick="completeStep({{ loop.index0 }})"
            >
                <span class="step-number">{{ loop.index }}.</span>
                {{ step }}
            </div>

            {% endfor %}

        </div>

    </div>


    <!-- VALMIS -->

    <div class="card finished" id="finished">

        <div class="finished-icon">🍽️</div>

        <div class="finished-title">
            Valmis!
        </div>

        <button class="reset" onclick="resetCooking()">
            Aloita alusta
        </button>

    </div>

</div>


<script>

const recipeId = {{ recipe.id }};
const storageKey = "recipe-" + recipeId + "-cooking";

let currentStep = 0;


/* -----------------------------
   Raaka-aineet
----------------------------- */

function toggleIngredients() {

    const content = document.getElementById("ingredientsContent");
    const arrow = document.getElementById("ingredientsArrow");

    if (content.style.display === "none") {

        content.style.display = "block";
        arrow.classList.add("open");

    } else {

        content.style.display = "none";
        arrow.classList.remove("open");

    }
}


function saveIngredients() {

    const checks = document.querySelectorAll(
        "#ingredientsContent input[type=checkbox]"
    );

    const values = [];

    checks.forEach(check => {
        values.push(check.checked);
    });

    const state = getState();

    state.ingredients = values;

    saveState(state);

    updateIngredientStyles();
}


function updateIngredientStyles() {

    const ingredients = document.querySelectorAll(".ingredient");

    ingredients.forEach(ingredient => {

        const checkbox = ingredient.querySelector("input");

        ingredient.classList.toggle(
            "checked",
            checkbox.checked
        );

    });
}


/* -----------------------------
   Tilanhallinta
----------------------------- */

function getState() {

    try {

        return JSON.parse(
            localStorage.getItem(storageKey)
        ) || {};

    } catch (e) {

        return {};

    }
}


function saveState(state) {

    localStorage.setItem(
        storageKey,
        JSON.stringify(state)
    );

}


/* -----------------------------
   Ruoanlaitto
----------------------------- */

function startCooking() {

    const state = getState();

    state.started = true;

    if (typeof state.currentStep !== "number") {
        state.currentStep = 0;
    }

    currentStep = state.currentStep;

    saveState(state);

    document.getElementById(
        "ingredientsContent"
    ).style.display = "none";

    document.getElementById(
        "ingredientsArrow"
    ).classList.remove("open");

    document.getElementById(
        "steps"
    ).style.display = "block";

    updateSteps();

}


function completeStep(index) {

    if (index !== currentStep) {
        return;
    }

    const steps = document.querySelectorAll(".step");

    if (!steps[index]) {
        return;
    }

    steps[index].classList.add("done");

    currentStep++;

    const state = getState();

    state.started = true;
    state.currentStep = currentStep;

    saveState(state);

    updateSteps();

}


function updateSteps() {

    const steps = document.querySelectorAll(".step");

    steps.forEach((step, index) => {

        step.classList.remove("active");

        if (index < currentStep) {
            step.classList.add("done");
        } else {
            step.classList.remove("done");
        }

        if (index === currentStep) {
            step.classList.add("active");
        }

    });


    const total = steps.length;

    if (currentStep < total) {

        document.getElementById(
            "progressText"
        ).textContent =
            "Vaihe " + (currentStep + 1) +
            " / " + total;

        document.getElementById(
            "progressBar"
        ).style.width =
            ((currentStep / total) * 100) + "%";

    } else {

        document.getElementById(
            "progressText"
        ).textContent =
            "Kaikki vaiheet valmiit";

        document.getElementById(
            "progressBar"
        ).style.width = "100%";

        document.getElementById(
            "finished"
        ).style.display = "block";

    }

}


/* -----------------------------
   Jatka tallennetusta kohdasta
----------------------------- */

function loadState() {

    const state = getState();

    if (Array.isArray(state.ingredients)) {

        const checks = document.querySelectorAll(
            "#ingredientsContent input[type=checkbox]"
        );

        checks.forEach((check, index) => {

            check.checked =
                state.ingredients[index] || false;

        });

        updateIngredientStyles();

    }


    if (state.started) {

        currentStep =
            typeof state.currentStep === "number"
                ? state.currentStep
                : 0;

        document.getElementById(
            "ingredientsContent"
        ).style.display = "none";

        document.getElementById(
            "ingredientsArrow"
        ).classList.remove("open");

        document.getElementById(
            "steps"
        ).style.display = "block";

        updateSteps();

    }

}


/* -----------------------------
   Aloita alusta
----------------------------- */

function resetCooking() {

    localStorage.removeItem(storageKey);

    location.reload();

}


loadState();

</script>

</body>
</html>
"""



@app.route("/api/next-meal")
def api_next_meal():
    meal = get_next_meal()

    if meal is None:
        return jsonify({"error": "No upcoming meal found"}), 404

    return jsonify(meal)


@app.route("/recipe/<int:recipe_id>/cook")
def recipe_cook(recipe_id):

    try:

        result = get_recipe(recipe_id)

        return render_template_string(
            RECIPE_TEMPLATE,
            recipe=result
        )

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


@app.route("/test")
def test():
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <h1>Iframe toimii</h1>
        <p>Tämä on täysin tavallinen HTML-sivu.</p>
    </body>
    </html>
    """

@app.route("/")
def index():

    return """
    <!DOCTYPE html>
    <html lang="fi">
    <head>
        <meta charset="UTF-8">
        <title>Reseptipalvelu</title>
    </head>

    <body style="
        font-family: system-ui;
        padding: 30px;
    ">

        <h1>Reseptipalvelu</h1>

        <p>
            <a href="/recipe/1">
                Huijarin butterchicken
            </a>
        </p>

    </body>
    </html>
    """


# ---------------------------------------------------------
# HTML
# ---------------------------------------------------------

HTML = """
<!DOCTYPE html>

<html lang="fi">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>{{ recipe.name }}</title>


<style>

* {
    box-sizing: border-box;
}


body {

    margin: 0;

    background: #f4f4f4;

    color: #222;

    font-family:
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}


.container {

    max-width: 900px;

    margin: auto;

    padding: 18px;

}


h1 {

    margin: 0 0 5px 0;

    font-size: 1.8rem;

}


.servings {

    color: #666;

    margin-bottom: 20px;

}


/* ---------------------------------------------------------
   CARD
--------------------------------------------------------- */

.card {

    background: white;

    border-radius: 16px;

    padding: 18px;

    margin-bottom: 18px;

    box-shadow:
        0 2px 8px rgba(0,0,0,.08);

}


.card-header {

    display: flex;

    align-items: center;

    justify-content: space-between;

    gap: 10px;

}


.card-header h2 {

    margin: 0;

}


.count {

    color: #666;

    font-size: .95rem;

}


/* ---------------------------------------------------------
   INGREDIENTS
--------------------------------------------------------- */

.ingredients-content {

    margin-top: 12px;

}


.ingredient {

    display: flex;

    align-items: center;

    gap: 12px;

    padding: 11px 4px;

    border-bottom: 1px solid #eee;

    cursor: pointer;

    font-size: 1.05rem;

}


.ingredient:last-child {

    border-bottom: none;

}


.ingredient input {

    width: 25px;

    height: 25px;

    flex-shrink: 0;

}


.ingredient.checked {

    color: #888;

}


.ingredient.checked .product {

    text-decoration: line-through;

}


.product {

    flex: 1;

}


.amount {

    color: #555;

    white-space: nowrap;

}


.start-button {

    width: 100%;

    margin-top: 18px;

    padding: 14px;

    border: none;

    border-radius: 12px;

    background: #555;

    color: white;

    font-size: 1.05rem;

    cursor: pointer;

}


.start-button:disabled {

    background: #ccc;

    cursor: not-allowed;

}


/* ---------------------------------------------------------
   COLLAPSED INGREDIENTS
--------------------------------------------------------- */

.ingredients-card.collapsed {

    padding-bottom: 12px;

}


.ingredients-card.collapsed
.ingredients-content {

    display: none;

}


.ingredients-card.collapsed
.start-button {

    display: none;

}


.toggle-button {

    border: none;

    background: transparent;

    font-size: 1.3rem;

    cursor: pointer;

    padding: 4px 8px;

}


/* ---------------------------------------------------------
   STEPS
--------------------------------------------------------- */

.steps {

    display: flex;

    flex-direction: column;

    gap: 10px;

}


.step {

    background: #fff;

    border-radius: 14px;

    padding: 16px;

    display: flex;

    gap: 14px;

    align-items: flex-start;

    transition: .2s;

}


.step-number {

    min-width: 36px;

    height: 36px;

    border-radius: 50%;

    background: #ddd;

    display: flex;

    align-items: center;

    justify-content: center;

    font-weight: bold;

}


.step-text {

    flex: 1;

    font-size: 1.05rem;

    line-height: 1.5;

}


.step-button {

    border: none;

    background: #eee;

    border-radius: 10px;

    width: 42px;

    height: 42px;

    font-size: 1.2rem;

    cursor: pointer;

    flex-shrink: 0;

}


.step.active {

    border: 3px solid #555;

    padding: 13px;

    box-shadow:
        0 3px 12px rgba(0,0,0,.15);

}


.step.active .step-number {

    background: #555;

    color: white;

}


.step.done {

    opacity: .4;

}


.step.done .step-text {

    text-decoration: line-through;

}


.step.done .step-number {

    background: #aaa;

    color: white;

}


.finished {

    text-align: center;

    padding: 25px;

    font-size: 1.2rem;

}


/* ---------------------------------------------------------
   NOTES
--------------------------------------------------------- */

.note {

    line-height: 1.5;

    margin-bottom: 12px;

}


.note:last-child {

    margin-bottom: 0;

}


/* ---------------------------------------------------------
   MOBILE / TABLET
--------------------------------------------------------- */

@media (max-width: 600px) {

    .container {

        padding: 10px;

    }


    h1 {

        font-size: 1.5rem;

    }


    .step-text {

        font-size: 1rem;

    }


    .ingredient {

        font-size: 1rem;

    }

}

</style>

</head>


<body>


<div class="container">


<!-- -------------------------------------------------------
     HEADER
-------------------------------------------------------- -->

<h1>
    {{ recipe.name }}
</h1>

<div class="servings">
    {{ recipe.servings }} annosta
</div>


<!-- -------------------------------------------------------
     INGREDIENTS
-------------------------------------------------------- -->

<div
    class="card ingredients-card"
    id="ingredients-card"
>


    <div class="card-header">

        <div>

            <h2>
                🛒 Raaka-aineet
            </h2>

            <div
                class="count"
                id="ingredient-count"
            >
                0 / {{ recipe.ingredients|length }} kerätty
            </div>

        </div>


        <button
            class="toggle-button"
            onclick="toggleIngredients()"
            aria-label="Avaa tai sulje raaka-aineet"
        >
            ▼
        </button>

    </div>


    <div
        class="ingredients-content"
        id="ingredients-content"
    >

        {% for ingredient in recipe.ingredients %}

        <div
            class="ingredient"
            onclick="toggleIngredient(this)"
        >

            <input
                type="checkbox"
                onchange="updateIngredient(this)"
                onclick="event.stopPropagation()"
            >

            <span class="product">
                {{ ingredient.product }}
            </span>

            <span class="amount">
                {{ ingredient.display_amount }}
            </span>

        </div>

        {% endfor %}


        <button
            id="start-button"
            class="start-button"
            onclick="startCooking()"
            disabled
        >
            Aloita valmistus
        </button>

    </div>

</div>


<!-- -------------------------------------------------------
     STEPS
-------------------------------------------------------- -->

<div
    class="card"
    id="steps-card"
>

    <h2>
        👨‍🍳 Valmistus
    </h2>


    <div
        class="steps"
        id="steps"
    >

        {% for step in recipe.steps %}

        <div
            class="step"
            data-step="{{ loop.index0 }}"
        >

            <div class="step-number">
                {{ loop.index }}
            </div>


            <div class="step-text">
                {{ step }}
            </div>


            <button
                class="step-button"
                onclick="completeStep({{ loop.index0 }})"
            >
                ✓
            </button>

        </div>

        {% endfor %}

    </div>


    <div
        id="finished"
        class="finished"
        style="display:none"
    >
        🎉 Resepti valmis!
    </div>

</div>


<!-- -------------------------------------------------------
     NOTES
-------------------------------------------------------- -->

{% if recipe.notes %}

<div class="card">

    <h2>
        💡 Vinkit
    </h2>


    {% for note in recipe.notes %}

    <div class="note">
        {{ note }}
    </div>

    {% endfor %}

</div>

{% endif %}


</div>


<script>

/*
 * ---------------------------------------------------------
 * RECIPE STATE
 * ---------------------------------------------------------
 */

const recipeId = {{ recipe.id }};

const storageKey =
    "recipe-progress-" + recipeId;


let state = {

    ingredients: [],

    steps: [],

    cookingStarted: false

};


/*
 * ---------------------------------------------------------
 * LOAD STATE
 * ---------------------------------------------------------
 */

function loadState() {

    const saved =
        localStorage.getItem(storageKey);

    if (!saved) {

        initializeState();

        return;

    }


    try {

        state = JSON.parse(saved);

    }

    catch (error) {

        initializeState();

    }

}


/*
 * ---------------------------------------------------------
 * INITIALIZE
 * ---------------------------------------------------------
 */

function initializeState() {

    state.ingredients =
        Array(
            {{ recipe.ingredients|length }}
        ).fill(false);


    state.steps =
        Array(
            {{ recipe.steps|length }}
        ).fill(false);


    state.cookingStarted = false;

    saveState();

}


/*
 * ---------------------------------------------------------
 * SAVE
 * ---------------------------------------------------------
 */

function saveState() {

    localStorage.setItem(
        storageKey,
        JSON.stringify(state)
    );

}


/*
 * ---------------------------------------------------------
 * INGREDIENTS
 * ---------------------------------------------------------
 */

function renderIngredients() {

    const rows =
        document.querySelectorAll(
            ".ingredient"
        );


    let collected = 0;


    rows.forEach((row, index) => {

        const checkbox =
            row.querySelector("input");


        checkbox.checked =
            !!state.ingredients[index];


        if (checkbox.checked) {

            row.classList.add("checked");

            collected++;

        }

        else {

            row.classList.remove("checked");

        }

    });


    const total =
        rows.length;


    document.getElementById(
        "ingredient-count"
    ).textContent =
        `${collected} / ${total} kerätty`;


    document.getElementById(
        "start-button"
    ).disabled =
        collected !== total;

}


function toggleIngredient(row) {

    const checkbox =
        row.querySelector("input");


    checkbox.checked =
        !checkbox.checked;


    updateIngredient(checkbox);

}


function updateIngredient(checkbox) {

    const row =
        checkbox.closest(".ingredient");


    const rows =
        Array.from(
            document.querySelectorAll(
                ".ingredient"
            )
        );


    const index =
        rows.indexOf(row);


    state.ingredients[index] =
        checkbox.checked;


    saveState();

    renderIngredients();

}


/*
 * ---------------------------------------------------------
 * START COOKING
 * ---------------------------------------------------------
 */

function startCooking() {

    if (
        !state.ingredients.every(
            value => value === true
        )
    ) {

        return;

    }


    state.cookingStarted = true;

    saveState();


    collapseIngredients();

    renderSteps();

}


/*
 * ---------------------------------------------------------
 * INGREDIENT COLLAPSE
 * ---------------------------------------------------------
 */

function collapseIngredients() {

    const card =
        document.getElementById(
            "ingredients-card"
        );


    card.classList.add("collapsed");


    const button =
        card.querySelector(
            ".toggle-button"
        );


    button.textContent = "▶";

}


function expandIngredients() {

    const card =
        document.getElementById(
            "ingredients-card"
        );


    card.classList.remove("collapsed");


    const button =
        card.querySelector(
            ".toggle-button"
        );


    button.textContent = "▼";

}


function toggleIngredients() {

    const card =
        document.getElementById(
            "ingredients-card"
        );


    if (
        card.classList.contains(
            "collapsed"
        )
    ) {

        expandIngredients();

    }

    else {

        collapseIngredients();

    }

}


/*
 * ---------------------------------------------------------
 * STEPS
 * ---------------------------------------------------------
 */

function renderSteps() {

    const steps =
        document.querySelectorAll(
            ".step"
        );


    let activeFound = false;


    steps.forEach((step, index) => {

        const done =
            !!state.steps[index];


        step.classList.toggle(
            "done",
            done
        );


        step.classList.remove(
            "active"
        );


        if (
            !done &&
            !activeFound
        ) {

            step.classList.add(
                "active"
            );

            activeFound = true;

        }

    });


    const allDone =
        state.steps.length > 0 &&
        state.steps.every(
            value => value === true
        );


    document.getElementById(
        "finished"
    ).style.display =
        allDone ? "block" : "none";


    if (allDone) {

        steps.forEach(
            step =>
                step.classList.remove(
                    "active"
                )
        );

    }

}


/*
 * ---------------------------------------------------------
 * COMPLETE STEP
 * ---------------------------------------------------------
 */

function completeStep(index) {

    if (state.steps[index]) {

        return;

    }


    state.steps[index] = true;

    saveState();

    renderSteps();


    /*
     * Etsi seuraava aktiivinen vaihe.
     */

    const steps =
        document.querySelectorAll(
            ".step"
        );


    for (
        let i = index + 1;
        i < steps.length;
        i++
    ) {

        if (
            !state.steps[i]
        ) {

            steps[i].scrollIntoView({
                behavior: "smooth",
                block: "center"
            });

            return;

        }

    }

}


/*
 * ---------------------------------------------------------
 * INITIALIZATION
 * ---------------------------------------------------------
 */

loadState();

renderIngredients();

renderSteps();


/*
 * Jos valmistus on jo aloitettu,
 * pidetään raaka-aineet suljettuina.
 */

if (state.cookingStarted) {

    collapseIngredients();

}

</script>


</body>

</html>
"""


# ---------------------------------------------------------
# START SERVER
# ---------------------------------------------------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


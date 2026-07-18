from flask import Flask, jsonify
import requests
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

app = Flask(__name__)

MOBIUS = "https://platform.iotcoss.ac.kr/api/proxy/swagger/Mobius"

HEADERS = {
    "X-M2M-RI":"123",
    "X-M2M-Origin":"S",
    "X-API-KEY":"REDACTED_MOBIUS_API_KEY_00000000",
    "X-AUTH-CUSTOM-LECTURE":"LCT_20260002",
    "X-AUTH-CUSTOM-CREATOR":"sjuADDHD",
    "Accept":"application/json"
}

model = RandomForestClassifier()


def load_logs():

    url = MOBIUS + "/ex/posture"

    r = requests.get(url, headers=HEADERS)

    cin = r.json()["m2m:cnt"]["m2m:cin"]

    rows = []

    for x in cin:

        con = x["con"]

        rows.append([
            x["ct"],
            con["mCRA"],
            int(con["neck_forward"])
        ])

    return pd.DataFrame(
        rows,
        columns=["time","angle","label"]
    )


@app.route("/predict")

def predict():

    df = load_logs()

    df["elapsed"] = (
        pd.to_datetime(df["time"])-
        pd.to_datetime(df["time"]).iloc[0]
    ).dt.total_seconds()/60

    X = df[["elapsed","angle"]]

    y = df["label"]

    model.fit(X,y)

    future = pd.DataFrame([[10,120]],columns=["elapsed","angle"])

    pred = model.predict(future)[0]

    return jsonify({
        "neck_forward":bool(pred)
    })


app.run(host="0.0.0.0",port=5000)

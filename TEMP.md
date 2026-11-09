\n#

"),
        (name: "WTF", value: "

`        description: "(.*)",`
`        versions: \[\((\d), (\d), (\d)\)\],`
`        name: "(.*)",`
`        dates: \["(\d{4}-\d{2}-\d{2})"\],`

Saponification
𝑯2𝑺𝑶4 / 𝑴𝒆𝑶𝑯
TMSH

---

`        \(name: "Date", value: "(\d{4}-\d{2}-\d{2})"\),`
```
        (name: "Date", value: "$1"),
```

---

        (name: "WTF", value: "2887 #3165"),
`        \(name: "WTF", value: "(\d{4}) #(\d{4})"\),`
        (name: "Index", value: "$1"),

`        \(name: "Description", value: "#(\d{4}) (\d{4}-\d{2}-\d{2});#(\d{4}) (\d{4}-\d{2}-\d{2})"\),`
```
        (name: "Index", value: "$1"),
        (name: "Date", value: "$2"),
```
```
        (name: "Index", value: "$3"),
        (name: "_Date", value: "$4"),
```

---

Проверить даты
        (name: "Species", value: "Helianthus annuus"),
        (name: "Name", value: "VIR+Бузулук"),

- 2 индекса хроматограмм: {Lipids=Neutral}{StereospecificNumbers=2}{Name=VIR-3714}{Date=2025-10-31}{Version=0.0.2}
- нет индекса: {Lipids=Neutral}{StereospecificNumbers=2}{Name=VIR-3110}{Date=2025-11-10}{Version=0.0.1}
- нет индекса: {Lipids=Neutral}{StereospecificNumbers=1&2&3}{Name=VIR-3675}{Date=2025-10-31}{Version=0.0.1}
- нет индекса: {Lipids=Neutral}{StereospecificNumbers=1&2&3}{Name=VIR-3675}{Date=2025-10-31}{Version=0.0.2}
- нет индекса: {Lipids=Neutral}{StereospecificNumbers=1&2&3}{Name=VIR-3675}{Date=2025-10-31}{Version=0.0.3}
- нет индекса: 

- {Lipids=Neutral}{StereospecificNumbers=2}{Name=VIR-3714}{Index=3190+3204}{Date=2025-10-31}{Version=0.0.2}.ron - какой из Index

---

на среде тамия
на среде bbm

`(        \(name: "Species", value: "(\S*).*"\),)`
```
        (name: "Genus", value: "$2"),
$1
```
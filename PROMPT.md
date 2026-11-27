Из таблиц [TABLE 1, TABLE 2] нужно создать следующиего вида csv:

`{Lipid=Total}{Index=1}{Name=Commodity}.csv`

```
DOI,Index,Date,Genus,Species,Name,Lipid,Method,Label,FattyAcid,Value
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Palmitic,"{""Carbon"":16,""Indices"":[]}",9.01
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Palmitoleic,"{""Carbon"":16,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.13
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Heptadecanoic,"{""Carbon"":17,""Indices"":[]}",0.11
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Stearic,"{""Carbon"":18,""Indices"":[]}",2.88
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Oleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",22.24
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Linoleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false}]}",44.91
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Pinolenic,"{""Carbon"":18,""Indices"":[{""Index"":5,""Triple"":false,""Parity"":false},{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false}]}",0.41
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Eicosenoic (cis-11),"{""Carbon"":20,""Indices"":[{""Index"":11,""Triple"":false,""Parity"":false}]}",0.12
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Linolenic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false},{""Index"":15,""Triple"":false,""Parity"":false}]}",0.65
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,"Eicosadienoic (cis-8,11)","{""Carbon"":20,""Indices"":[{""Index"":8,""Triple"":false,""Parity"":false},{""Index"":11,""Triple"":false,""Parity"":false}]}",0.79
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,"Eicosadienoic (cis-11,14)","{""Carbon"":20,""Indices"":[{""Index"":11,""Triple"":false,""Parity"":false},{""Index"":14,""Triple"":false,""Parity"":false}]}",2.72
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Sciadonic,"{""Carbon"":20,""Indices"":[{""Index"":5,""Triple"":false,""Parity"":false},{""Index"":11,""Triple"":false,""Parity"":false},{""Index"":14,""Triple"":false,""Parity"":false}]}",14.50
10.1016/j.indcrop.2019.111917,1,2020-01-01,Torreya,Torreya grandis,Mufei,Total,Experimental,Juniperonic,"{""Carbon"":20,""Indices"":[{""Index"":5,""Triple"":false,""Parity"":false},{""Index"":11,""Triple"":false,""Parity"":false},{""Index"":14,""Triple"":false,""Parity"":false},{""Index"":17,""Triple"":false,""Parity"":false}]}",0.44
```

Из таблиц [Table 2] нужно создать следующиего вида csv:

`{Lipid=Triacylglycerol}{Index=1}{Name=Commodity}.csv`

```
DOI,Index,Date,Genus,Species,Name,Lipid,StereospecificNumbers,Method,Label,FattyAcid,Value
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Myristic,"{""Carbon"":14,""Indices"":[]}",0.001
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Palmitic,"{""Carbon"":16,""Indices"":[]}",0.07
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Palmitoleic,"{""Carbon"":16,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.002
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Stearic,"{""Carbon"":18,""Indices"":[]}",0.048
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Oleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.278
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Linoleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false}]}",0.587
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Linolenic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false},{""Index"":15,""Triple"":false,""Parity"":false}]}",0.001
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Arachidic,"{""Carbon"":20,""Indices"":[]}",0.003
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Eicosenoic (cis-11),"{""Carbon"":20,""Indices"":[{""Index"":11,""Triple"":false,""Parity"":false}]}",0.001
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Behenic,"{""Carbon"":22,""Indices"":[]}",0.007
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Erucic (cis-13),"{""Carbon"":22,""Indices"":[{""Index"":13,""Triple"":false,""Parity"":false}]}",0.001
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Lignoceric,"{""Carbon"":24,""Indices"":[]}",0.003
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,1,Experimental,Palmitic,"{""Carbon"":16,""Indices"":[]}",0.109
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,1,Experimental,Palmitoleic,"{""Carbon"":16,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.006
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,1,Experimental,Stearic,"{""Carbon"":18,""Indices"":[]}",0.019
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,1,Experimental,Oleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.171
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,1,Experimental,Linoleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false}]}",0.7
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,2,Experimental,Palmitic,"{""Carbon"":16,""Indices"":[]}",0.014
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,2,Experimental,Palmitoleic,"{""Carbon"":16,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.004
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,2,Experimental,Stearic,"{""Carbon"":18,""Indices"":[]}",0.012
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,2,Experimental,Oleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.315
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,2,Experimental,Linoleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false}]}",0.657
```

---

Из таблиц [Table 3] нужно создать следующиего вида csv:

`{Lipid=Triacylglycerol}{Index=1}{Name=Commodity}.csv`

```
DOI,Index,Date,Genus,Species,Name,Lipid,StereospecificNumbers,Method,Label,FattyAcid,Value
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Myristic,"{""Carbon"":14,""Indices"":[]}",0.001
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Palmitic,"{""Carbon"":16,""Indices"":[]}",0.07
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Palmitoleic,"{""Carbon"":16,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.002
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Stearic,"{""Carbon"":18,""Indices"":[]}",0.048
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Oleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.278
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Linoleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false}]}",0.587
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Linolenic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false},{""Index"":15,""Triple"":false,""Parity"":false}]}",0.001
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Arachidic,"{""Carbon"":20,""Indices"":[]}",0.003
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Eicosenoic (cis-11),"{""Carbon"":20,""Indices"":[{""Index"":11,""Triple"":false,""Parity"":false}]}",0.001
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Behenic,"{""Carbon"":22,""Indices"":[]}",0.007
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Erucic (cis-13),"{""Carbon"":22,""Indices"":[{""Index"":13,""Triple"":false,""Parity"":false}]}",0.001
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,"1,2,3",Experimental,Lignoceric,"{""Carbon"":24,""Indices"":[]}",0.003
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,1,Experimental,Palmitic,"{""Carbon"":16,""Indices"":[]}",0.109
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,1,Experimental,Palmitoleic,"{""Carbon"":16,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.006
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,1,Experimental,Stearic,"{""Carbon"":18,""Indices"":[]}",0.019
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,1,Experimental,Oleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.171
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,1,Experimental,Linoleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false}]}",0.7
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,2,Experimental,Palmitic,"{""Carbon"":16,""Indices"":[]}",0.014
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,2,Experimental,Palmitoleic,"{""Carbon"":16,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.004
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,2,Experimental,Stearic,"{""Carbon"":18,""Indices"":[]}",0.012
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,2,Experimental,Oleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false}]}",0.315
10.1007/s11746-997-0016-1,1,1997-08-01,Helianthus,Helianthus annuus,Commodity,Triacylglycerol,2,Experimental,Linoleic,"{""Carbon"":18,""Indices"":[{""Index"":9,""Triple"":false,""Parity"":false},{""Index"":12,""Triple"":false,""Parity"":false}]}",0.657
```

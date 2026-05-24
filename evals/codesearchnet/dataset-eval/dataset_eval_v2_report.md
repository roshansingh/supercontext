# CodeSearchNet Eval v2: Full-Corpus NDCG vs Published Baselines

**Generated:** 2026-05-24T16:53:59.107572+00:00  
**Corpus:** 457,461 Python functions  
**Queries:** 92 evaluated, 7 skipped  
**Runtime:** 211.4s

---

## Leaderboard — NDCG Within (Python)

NDCG computed only over human-annotated functions. Higher = better.

| Rank | Model | NDCG Within | Source |
|------|-------|-------------|--------|
| 1 | Our TF-IDF baseline | **0.8263** | **This eval** |
| 2 | Our SC-enhanced | **0.8234** | **This eval** |
| 3 | ElasticSearch | **0.4060** | Husain et al. 2019 |
| 4 | 1D-CNN | **0.3410** | Husain et al. 2019 |
| 5 | Neural BoW | **0.2790** | Husain et al. 2019 |
| 6 | biRNN | **0.1690** | Husain et al. 2019 |

## Leaderboard — NDCG All (Python)

NDCG computed over all ~457K functions (top-1000 ranking window). Higher = better.

| Rank | Model | NDCG All | Source |
|------|-------|----------|--------|
| 1 | ElasticSearch | **0.2560** | Husain et al. 2019 |
| 2 | Neural BoW | **0.2230** | Husain et al. 2019 |
| 3 | 1D-CNN | **0.1660** | Husain et al. 2019 |
| 4 | Our SC-enhanced | **0.1076** | **This eval** |
| 5 | Our TF-IDF baseline | **0.1069** | **This eval** |
| 6 | biRNN | **0.0640** | Husain et al. 2019 |

---

## Win Rates (SC-enhanced vs TF-IDF baseline)

| Metric | SC wins | Text wins | Ties |
|--------|---------|-----------|------|
| NDCG Within | 7 | 5 | 80 |
| NDCG All    | 31 | 10 | 51 |

---

## Per-Query Results

| Query | Matched | Within(Text) | Within(SC) | All(Text) | All(SC) |
|-------|---------|-------------|-----------|----------|--------|
| aes encryption | 6 | 0.9763 | 0.9763 | 0.2273 | 0.2270 |
| all permutations of a list | 9 | 0.8588 | 0.8588 | 0.1034 | 0.1040 |
| binomial distribution | 7 | 0.9118 | 0.9223 | 0.2426 | 0.2396 |
| buffered file reader read text | 4 | 0.8146 | 0.8146 | 0.0000 | 0.0000 |
| concatenate several file remove header lines | 7 | 0.9816 | 0.9816 | 0.1969 | 0.1990 |
| confusion matrix | 7 | 0.8266 | 0.8266 | 0.2198 | 0.2196 |
| convert a date string into yyyymmdd | 8 | 0.9007 | 0.7471 | 0.1472 | 0.1536 |
| convert a utc time to epoch | 9 | 0.7318 | 0.7318 | 0.1215 | 0.1219 |
| convert decimal to hex | 9 | 0.8557 | 0.9390 | 0.0000 | 0.0000 |
| convert html to pdf | 7 | 0.9607 | 0.9607 | 0.1626 | 0.1637 |
| convert int to bool | 3 | 0.9828 | 0.9828 | 0.0000 | 0.0000 |
| convert int to string | 4 | 0.5151 | 0.5151 | 0.0000 | 0.0000 |
| convert json to csv | 9 | 0.6498 | 0.6498 | 0.1509 | 0.1512 |
| convert string to number | 3 | 0.8076 | 0.8076 | 0.0000 | 0.0000 |
| converting uint8 array to image | 7 | 0.7924 | 0.8229 | 0.0000 | 0.0000 |
| copy to clipboard | 6 | 0.7512 | 0.7512 | 0.1047 | 0.1048 |
| copying a file to a path | 5 | 0.7241 | 0.7746 | 0.0000 | 0.0000 |
| create cookie | 5 | 0.9489 | 0.9489 | 0.1541 | 0.1907 |
| custom http error response | 4 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| deducting the median from each column | 7 | 0.7739 | 0.7739 | 0.1038 | 0.1038 |
| deserialize json | 5 | 0.9451 | 0.9451 | 0.1756 | 0.1756 |
| encode url | 4 | 0.8595 | 0.8595 | 0.0000 | 0.0000 |
| export to excel | 6 | 0.9198 | 0.9198 | 0.0000 | 0.0000 |
| extract data from html content | 4 | 0.8915 | 0.8915 | 0.1077 | 0.1077 |
| extract latitude and longitude from given input | 7 | 0.7099 | 0.7099 | 0.1314 | 0.1314 |
| extracting data from a text file | 7 | 0.8198 | 0.8198 | 0.0000 | 0.0000 |
| filter array | 3 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| find int in string | 3 | 0.7098 | 0.7098 | 0.0000 | 0.0000 |
| finding time elapsed using a timer | 3 | 1.0000 | 1.0000 | 0.1305 | 0.1307 |
| format date | 3 | 1.0000 | 1.0000 | 0.1071 | 0.1076 |
| fuzzy match ranking | 4 | 0.9915 | 0.9915 | 0.1416 | 0.1417 |
| get all parents of xml node | 3 | 0.5000 | 0.5000 | 0.0000 | 0.0000 |
| get current ip address | 7 | 0.7163 | 0.6710 | 0.1261 | 0.1261 |
| get current observable value | 4 | 0.9448 | 0.9448 | 0.1309 | 0.1307 |
| get current process id | 4 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| get executable path | 9 | 0.9702 | 0.9702 | 0.2290 | 0.2297 |
| get inner html | 6 | 0.7136 | 0.7136 | 0.1379 | 0.1373 |
| get name of enumerated value | 6 | 0.9608 | 0.9608 | 0.0000 | 0.0000 |
| get the description of a http status code | 7 | 0.6954 | 0.6954 | 0.0000 | 0.0000 |
| group by count | 4 | 0.5151 | 0.5151 | 0.0000 | 0.0000 |
| hash set for counting distinct elements | 6 | 0.7076 | 0.7076 | 0.1105 | 0.1094 |
| heatmap from 3d coordinates | 8 | 0.8331 | 0.8331 | 0.1108 | 0.1124 |
| how to check if a checkbox is checked | 5 | 0.8165 | 0.8165 | 0.1063 | 0.1063 |
| how to determine a string is a valid word | 6 | 0.6952 | 0.6952 | 0.0000 | 0.0000 |
| how to empty array | 4 | 0.7277 | 0.7277 | 0.1262 | 0.1262 |
| how to extract zip file recursively | 4 | 1.0000 | 1.0000 | 0.1206 | 0.1207 |
| how to get current date | 8 | 0.6062 | 0.6062 | 0.0000 | 0.0000 |
| how to get database table name | 5 | 0.5413 | 0.5413 | 0.0000 | 0.0000 |
| how to get html of website | 5 | 0.5000 | 0.5000 | 0.0000 | 0.0000 |
| how to make the checkbox checked | 4 | 0.7648 | 0.7648 | 0.0000 | 0.0000 |
| how to randomly pick a number | 5 | 0.9069 | 0.9069 | 0.0000 | 0.0000 |
| how to read .csv file in an efficient way? | 5 | 0.8288 | 0.8288 | 0.1021 | 0.1025 |
| how to read the contents of a .gz compressed file? | 4 | 0.7191 | 0.7191 | 0.0000 | 0.0000 |
| how to reverse a string | 4 | 0.9832 | 0.9832 | 0.0000 | 0.0000 |
| html entities replace | 8 | 0.8906 | 0.8906 | 0.1727 | 0.1731 |
| httpclient post json | 3 | 0.9197 | 0.9197 | 0.1651 | 0.1666 |
| initializing array | 4 | 0.9639 | 0.6399 | 0.0000 | 0.0000 |
| json to xml conversion | 6 | 0.5095 | 0.5095 | 0.1198 | 0.1203 |
| k means clustering | 7 | 0.9674 | 0.9674 | 0.7038 | 0.7038 |
| linear regression | 7 | 0.9320 | 0.9320 | 0.3809 | 0.3809 |
| map to json | 5 | 1.0000 | 1.0000 | 0.1686 | 0.1686 |
| matrix multiply | 3 | 0.6806 | 0.6806 | 0.1745 | 0.1746 |
| memoize to disk  - persistent memoization | 5 | 0.9327 | 0.9327 | 0.1399 | 0.1399 |
| nelder mead optimize | 6 | 0.8481 | 0.8481 | 0.2754 | 0.2774 |
| normal distribution | 6 | 0.8118 | 0.8458 | 0.2130 | 0.2148 |
| output to html file | 5 | 0.8715 | 0.8715 | 0.0000 | 0.0000 |
| parse binary file to custom class | 6 | 0.6648 | 0.7220 | 0.0000 | 0.0000 |
| parse json file | 3 | 0.8076 | 0.8076 | 0.1238 | 0.1241 |
| parse query string in url | 5 | 0.8446 | 0.8446 | 0.1352 | 0.1357 |
| positions of substrings in string | 5 | 0.9217 | 0.9217 | 0.1065 | 0.1067 |
| postgresql connection | 7 | 0.9348 | 0.9348 | 0.2262 | 0.2268 |
| pretty print json | 5 | 0.9697 | 0.9697 | 0.1833 | 0.1870 |
| print model summary | 6 | 0.7304 | 0.7727 | 0.1443 | 0.1461 |
| priority queue | 5 | 0.9515 | 0.9515 | 0.1750 | 0.1750 |
| randomly extract x items from a list | 7 | 0.7163 | 0.7163 | 0.1046 | 0.1051 |
| read properties file | 4 | 1.0000 | 1.0000 | 0.1553 | 0.1553 |
| read text file line by line | 5 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| reading element from html - <td> | 6 | 0.8347 | 0.8347 | 0.2665 | 0.2665 |
| readonly array | 3 | 1.0000 | 1.0000 | 0.1526 | 0.1519 |
| regex case insensitive | 6 | 1.0000 | 1.0000 | 0.1284 | 0.1284 |
| replace in file | 4 | 0.9324 | 0.9324 | 0.0000 | 0.0000 |
| save list to file | 5 | 0.6183 | 0.5889 | 0.0000 | 0.0000 |
| scatter plot | 6 | 0.9836 | 0.9836 | 0.1726 | 0.1721 |
| sending binary data over a serial connection | 9 | 0.9550 | 0.9550 | 0.1638 | 0.1638 |
| set working directory | 10 | 0.6217 | 0.6217 | 0.1711 | 0.1705 |
| socket recv timeout | 5 | 0.8851 | 0.8851 | 0.1369 | 0.1386 |
| sort string list | 5 | 0.8503 | 0.8503 | 0.1030 | 0.1041 |
| sorting multiple arrays based on another arrays sorted order | 4 | 0.6806 | 0.6806 | 0.1314 | 0.1314 |
| string similarity levenshtein | 7 | 0.9791 | 0.9595 | 0.1701 | 0.1705 |
| unique elements | 6 | 0.8642 | 0.8642 | 0.1562 | 0.1561 |
| unzipping large files | 6 | 0.7106 | 0.7106 | 0.0000 | 0.0000 |
| write csv | 5 | 0.9739 | 0.9739 | 0.1851 | 0.1851 |

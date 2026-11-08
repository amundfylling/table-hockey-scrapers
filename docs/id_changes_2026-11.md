# Player ids changed by the H2H data audit fixes (2026-11-08)

Every (old id, new id) pair that changed between the data before and after the fixes, per source, with the
player's name and the number of game sides that moved. `data/id_changes.csv` holds the 154 clean renames
(the old id no longer appears anywhere and all of it moved to one new id). The rows marked **split** are old ids
that carried two people: the old id stays with the first person, the other person's games move to their own id
(or, for 50000192, both halves move), so they are not in `id_changes.csv`.

| source | old id | new id | name | game sides | kind |
|---|---:|---:|---|---:|---|
| escore | 40000875 | 50000198 | Braiens Gorsanovs | 125 | rename |
| escore | 40001484 | 50000299 | Tina Gorsanova | 116 | rename |
| escore | 40000745 | 2005 | Elina Gala | 62 | rename |
| galdahokejs | 50000023 | 8566 | Raivis Miglinieks | 376 | rename |
| galdahokejs | 50000039 | 194 | Salvis Skarainis | 216 | rename |
| galdahokejs | 50000192 | 8424 | Margarita Ābele | 178 | split |
| galdahokejs | 50000045 | 2071 | Gunārs Buls | 110 | rename |
| galdahokejs | 50000103 | 9009 | Timur Mihhaljov | 104 | rename |
| galdahokejs | 50000076 | 13604 | Ilgvars Pavlovskis | 78 | rename |
| galdahokejs | 50000414 | 11930 | Elēna Rācenāja | 67 | rename |
| galdahokejs | 50000194 | 13407 | Lāsma Bezdelīga | 54 | rename |
| galdahokejs | 50000266 | 1613 | Eike Rompa | 53 | rename |
| galdahokejs | 50000294 | 9739 | Katrīna Ļihačova | 50 | rename |
| galdahokejs | 50000234 | 9310043 | Dmytro Kudrytsky | 38 | rename |
| galdahokejs | 50000192 | 4773 | Markuss Ābele | 36 | split |
| galdahokejs | 9675286 | 14661 | Michael Moravec | 33 | rename |
| galdahokejs | 50000297 | 184 | Igor Saveljev | 13 | rename |
| galdahokejs | 50000302 | 9271 | Gintautas Remeika | 13 | rename |
| trefik | 21000298 | 9070067 | Karel Konečný | 3542 | rename |
| trefik | 21000155 | 9070080 | Michal Zunka | 3265 | rename |
| trefik | 21000197 | 9079309 | Dušan Krása | 3083 | rename |
| trefik | 21000202 | 9070081 | Jan Hlůžek | 2993 | rename |
| trefik | 21000612 | 9070222 | Miroslav Hubáček ml. | 2836 | rename |
| trefik | 21000518 | 9070177 | Markéta Pilařová | 2791 | rename |
| trefik | 21000662 | 9070016 | František Suchý | 2728 | rename |
| trefik | 21000420 | 9070047 | Josef Jelínek | 2699 | rename |
| trefik | 21000663 | 9070221 | Miroslav Hubáček st. | 2504 | rename |
| trefik | 21000666 | 9070002 | Vladimír Studnička | 2327 | rename |
| trefik | 21000327 | 9652310 | David Brdíček | 2064 | rename |
| trefik | 21000243 | 9070417 | Petr Sládek | 2031 | rename |
| trefik | 21000160 | 9651418 | Radim Nevrlík | 1926 | rename |
| trefik | 21000726 | 9070003 | Pavel Chaluš | 1905 | rename |
| trefik | 21000207 | 9079381 | Radek Matouš | 1764 | rename |
| trefik | 21000264 | 9070007 | Aleš Kraus | 1763 | rename |
| trefik | 21000265 | 9070006 | Josef Kraus | 1569 | rename |
| trefik | 21000312 | 9070008 | Tereza Krausová | 1544 | rename |
| trefik | 21000204 | 9079349 | Martin Kouba | 1433 | rename |
| trefik | 21000425 | 9070491 | Marie Vargová | 1226 | rename |
| trefik | 21000288 | 9070028 | Jan Baščan | 1145 | rename |
| trefik | 21000195 | 9070011 | Karel Krejčík | 1136 | rename |
| trefik | 21000661 | 9070518 | Tomáš Rumler | 1095 | rename |
| trefik | 21000361 | 9070019 | Libor Grabec | 1086 | rename |
| trefik | 21000477 | 9070198 | Josef Bečvář | 1077 | rename |
| trefik | 21000772 | 9070187 | Kristýna Baščanová | 1029 | rename |
| trefik | 21000727 | 9070014 | Luděk Solar | 989 | rename |
| trefik | 21000332 | 9070020 | Antonín Šrajer / Antonín šrajer | 985 | rename |
| trefik | 21000260 | 9070490 | Anežka Vargová | 957 | rename |
| trefik | 9656211 | 14662 | Martin Moravec | 898 | rename |
| trefik | 9675286 | 14661 | Michael Moravec | 871 | rename |
| trefik | 21000771 | 9260065 | Martin Králik | 815 | rename |
| trefik | 21000462 | 9652978 | Lukáš Jílek | 807 | rename |
| trefik | 21000219 | 9070292 | Lukáš Vacek | 723 | rename |
| trefik | 21000613 | 9650551 | Evžen Vavruška | 681 | rename |
| trefik | 21000566 | 9652312 | Erik Šlechta | 648 | rename |
| trefik | 21000429 | 9079156 | Petr Šurýn | 623 | rename |
| trefik | 21000306 | 9655710 | Lukáš Staněk | 585 | rename |
| trefik | 21000855 | 9070072 | Martin Drapák | 568 | rename |
| trefik | 21000706 | 9070051 | Magdalena Malá | 558 | rename |
| trefik | 21000342 | 9070088 | Pavel Soukup | 503 | rename |
| trefik | 21000730 | 9070027 | Aleš Horčička | 490 | rename |
| trefik | 21000620 | 9650671 | Miloslav Fajmon | 420 | rename |
| trefik | 21000526 | 9650647 | Tomáš Václavek | 384 | rename |
| trefik | 21000335 | 9260147 | Tomáš Zamutovský | 382 | rename |
| trefik | 21000337 | 9150285 | Barnabas Parkanszki | 366 | rename |
| trefik | 21000615 | 9150166 | Máté Szabó | 331 | rename |
| trefik | 21000617 | 9150177 | Zoltán Szabó | 328 | rename |
| trefik | 21000648 | 9070689 | David Müller | 320 | rename |
| trefik | 21000567 | 9650096 | Břetislav Anft | 319 | rename |
| trefik | 21000134 | 9079014 | Michael Černý | 309 | rename |
| trefik | 21000645 | 9079030 | Michal Heczko | 308 | rename |
| trefik | 21000222 | 9450002 | Kristijan Curkovic | 296 | rename |
| trefik | 21000561 | 9079176 | Daniel Elisek | 277 | rename |
| trefik | 21000845 | 9260054 | Martin Kácha | 255 | rename |
| trefik | 21000277 | 9658418 | Adam Sowa | 246 | rename |
| trefik | 46 | 1471 | Arseniy Stolyarov / Stolyarov Arseniy | 239 | split |
| trefik | 21000487 | 9650815 | Milan Kolář | 232 | rename |
| trefik | 21000115 | 9669500 | Jakub Saj / Saj Jakub | 229 | rename |
| trefik | 21000584 | 232 | Aleksey Zakharov | 227 | rename |
| trefik | 21000282 | 9450001 | Marko Curkovic | 214 | rename |
| trefik | 21000227 | 9655177 | Tomislav Cigula | 213 | rename |
| trefik | 21000387 | 9260079 | Tomáš Miženko | 190 | rename |
| trefik | 21000588 | 9150281 | Tamas Molnar | 187 | rename |
| trefik | 21000759 | 9260029 | Emil Galoci / Emil Galoči | 176 | rename |
| trefik | 21001032 | 9070066 | Petr Jarolím | 162 | rename |
| trefik | 21000881 | 9260064 | Juraj Králik | 160 | rename |
| trefik | 21000488 | 237 | Alexandr Miloradov | 158 | rename |
| trefik | 21000586 | 235 | Ivan Zakharov | 158 | rename |
| trefik | 21000568 | 9651332 | Robert Mašek | 155 | rename |
| trefik | 21000623 | 9652803 | Jan Foršt | 155 | rename |
| trefik | 21001025 | 9070197 | Roman Vondrouš | 154 | rename |
| trefik | 21000449 | 228 | Mariya Miloradova | 146 | rename |
| trefik | 21000577 | 9652185 | Matúš Repovský | 133 | rename |
| trefik | 21000147 | 9655246 | Lukáš Musil | 129 | rename |
| trefik | 21000774 | 9260017 | Patrik Csank | 127 | rename |
| trefik | 21000804 | 9020015 | Andreas Steger | 127 | rename |
| trefik | 16444 | 9674878 | Daniel Jerabek | 126 | split |
| trefik | 21000704 | 9650817 | Milan Pašek | 112 | rename |
| trefik | 21000191 | 3362 | Evgenii Solovev | 108 | rename |
| trefik | 21000933 | 9260045 | Jozef Hrnčirík | 99 | rename |
| trefik | 21000700 | 9651947 | Adam Ducháček | 96 | rename |
| trefik | 21000852 | 9270027 | Sergej Vasiljev | 93 | rename |
| trefik | 21000854 | 9020014 | Andreas Schwenter | 87 | rename |
| trefik | 21000750 | 3020 | Mihail Mihin | 86 | rename |
| trefik | 21000797 | 9020002 | Florian Dietachmayr | 84 | rename |
| trefik | 21000805 | 9020003 | Stefan Dietachmayr | 84 | rename |
| trefik | 21000749 | 9150016 | László Bobák | 83 | rename |
| trefik | 21000017 | 9674681 | Václav Macek ml. | 81 | rename |
| trefik | 21000867 | 9150098 | Evelin Soltész | 75 | rename |
| trefik | 21000871 | 9150046 | Patricia Kapuvári | 73 | rename |
| trefik | 21000597 | 9450003 | Vjekoslav Kufrin | 69 | rename |
| trefik | 21000699 | 9650816 | Jiří Boldiš | 65 | rename |
| trefik | 21000614 | 9650481 | Akos Szabó | 64 | rename |
| trefik | 21000758 | 9240218 | Alexandr Mihin | 60 | rename |
| trefik | 21000888 | 9240207 | Mikhail Martynov | 58 | rename |
| trefik | 21000947 | 9220239 | Espen Selbaek | 56 | rename |
| trefik | 21000792 | 9240406 | Yuriy Ivanov | 49 | rename |
| trefik | 21000897 | 9180005 | Pablo Bonta | 49 | rename |
| trefik | 21000906 | 9180006 | Gionni Bosco | 49 | rename |
| trefik | 21000907 | 9180010 | Marco Galvagno | 49 | rename |
| trefik | 21000949 | 9260057 | Marián Kapusta | 49 | rename |
| trefik | 21000950 | 9150052 | Tamás Kiss | 49 | rename |
| trefik | 21000890 | 9100123 | Markus Laakso | 47 | rename |
| trefik | 21000844 | 9310043 | Dmytro Kudrytsky | 45 | rename |
| trefik | 21000870 | 9070423 | Jakub Bauer | 45 | rename |
| trefik | 21000368 | 5434 | Antti Suojanen | 44 | rename |
| trefik | 21000848 | 9080040 | Peter Orum | 44 | rename |
| trefik | 21000849 | 9020004 | Thomas Dietachmayr | 44 | rename |
| trefik | 21000893 | 9240132 | Igor Kashentsev | 43 | rename |
| trefik | 21000900 | 9180001 | Antonino Bosco | 43 | rename |
| trefik | 21000492 | 9656581 | Micael Palm | 42 | rename |
| trefik | 21000650 | 9280637 | Dan Engdahl | 41 | rename |
| trefik | 21000955 | 9200118 | Janis Kirsis | 41 | rename |
| trefik | 21000651 | 9200330 | Intars Zubeckis | 40 | rename |
| trefik | 21000799 | 9150067 | Gaspar Létay | 40 | rename |
| trefik | 21000703 | 9652979 | Tomáš Vácha | 36 | rename |
| trefik | 1251 | 1234 | Rjavec Bernard | 35 | split |
| trefik | 21000552 | 627 | Vyacheslav Potehin | 35 | rename |
| trefik | 21000654 | 9652755 | Evgeniy Sereda | 35 | rename |
| trefik | 1266 | 10603 | Beat Luginbuehl | 34 | rename |
| trefik | 10137 | 5438 | Regula Gergely | 34 | split |
| trefik | 21000296 | 10530 | Allan Lorand | 34 | rename |
| trefik | 21000606 | 9650086 | Yevhen Rykun | 34 | rename |
| trefik | 21000795 | 9290060 | Stefan Wyss | 32 | rename |
| trefik | 1753 | 1621 | Dietze Valentin | 31 | split |
| trefik | 21000173 | 20001919 | Prauda Rodi | 31 | rename |
| trefik | 9673226 | 9673797 | Jan Čermák | 30 | split |
| trefik | 20002049 | 9675480 | Martin Dvořák | 29 | rename |
| trefik | 21000569 | 9654530 | Iveta Okálová | 29 | rename |
| trefik | 21000932 | 9150016 | Bobák Lászlo | 28 | rename |
| trefik | 21001008 | 9070078 | Silvestr Novotný | 26 | rename |
| trefik | 21000921 | 9150041 | Zoltán Illés | 24 | rename |
| trefik | 21000923 | 9150081 | Attila Nógrádi | 24 | rename |
| trefik | 21001013 | 9070258 | Miroslav Vondrouš | 24 | rename |
| trefik | 21000176 | 9669500 | Saj Jakub | 20 | rename |
| trefik | 21001017 | 9070111 | Miroslav Müller | 20 | rename |
| trefik | 21000987 | 9070020 | Šrajer Antonín | 19 | rename |
| trefik | 21000656 | 231 | Mikhail Margolis | 18 | rename |
| trefik | 21001000 | 9070136 | Leoš Horčička | 17 | rename |
| trefik | 21001009 | 9070085 | Pavel Navrátil | 17 | rename |
| trefik | 21000839 | 9070092 | Aleš Lehký | 15 | rename |
| trefik | 21000927 | 9150131 | Zsolt Vlkán | 15 | rename |
| trefik | 21000991 | 9070047 | Jelínek Josef | 9 | rename |
| trefik | 21001022 | 9070222 | ml. Hubáček Miroslav | 9 | rename |

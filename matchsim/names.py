"""Name pools by nationality for fictional players and managers.

Pools avoid surnames strongly associated with famous footballers so that random
first-name / last-name pairs never recreate a real player. Weights roughly follow
the nationality mix of a modern Premier League squad list.
"""
from __future__ import annotations

# nationality: (weight, first names, last names)
NATIONALITIES = {
    "England": (30, [
        "Aaron", "Alfie", "Archie", "Ben", "Callum", "Charlie", "Connor", "Danny", "Dominic",
        "Ethan", "Freddie", "George", "Harvey", "Jacob", "Jake", "Joe", "Jordan",
        "Josh", "Kieran", "Leon", "Lewis", "Louie", "Marcus", "Mason", "Max", "Morgan", "Nathan",
        "Oliver", "Ollie", "Reece", "Rhys", "Ryan", "Sam", "Theo", "Toby", "Tom", "Tyler", "Zach",
    ], [
        "Ashworth", "Barlow", "Bramhall", "Blackwood", "Bradshaw", "Brennan", "Calloway",
        "Chadwick", "Cartwright", "Crossley", "Dawson", "Eastwood", "Ellison", "Fairclough",
        "Fenwick", "Greaves", "Hargreaves", "Hartigan", "Holloway", "Hutchins", "Kerrigan", "Lawton",
        "Mallory", "Marsden", "Moorcroft", "Pickering", "Prentice", "Radcliffe", "Rowntree", "Selby",
        "Shelton", "Stanton", "Thackeray", "Thorne", "Wainwright", "Whitaker", "Whitmore", "Yardley",
    ]),
    "France": (8, [
        "Adrien", "Bastien", "Benjamin", "Clément", "Corentin", "Damien", "Enzo", "Florian", "Hugo",
        "Jules", "Killian", "Lucas", "Mattéo", "Maxence", "Nolan", "Rayan", "Romain", "Théo",
        "Tanguy", "Yanis",
    ], [
        "Aubert", "Barbier", "Bertin", "Caron", "Chevalier", "Delacroix", "Dufresne", "Fabre",
        "Garnier", "Joubert", "Lacombe", "Lemaire", "Marchand", "Mercier", "Moreau", "Perrin",
        "Roussel", "Thibault", "Vasseur", "Vernet",
    ]),
    "Spain": (6, [
        "Adrián", "Álvaro", "Borja", "Dani", "Diego", "Hugo", "Iker", "Javi", "Marcos", "Mario",
        "Mikel", "Nacho", "Óscar", "Pablo", "Pau", "Rodrigo", "Santi", "Unai",
    ], [
        "Aldana", "Arrieta", "Bermejo", "Castell", "Echeverría", "Garrido", "Ibarra", "Lucero",
        "Navarrete", "Olmedo", "Palomares", "Quintana", "Salcedo", "Sandoval", "Urrutia", "Zabala",
    ]),
    "Portugal": (4, [
        "André", "Bruno", "Diogo", "Duarte", "Gonçalo", "Hélder", "João", "Nuno", "Rafael", "Rúben",
        "Tiago", "Vasco",
    ], [
        "Amaral", "Baptista", "Cardoso", "Carvalhal", "Esteves", "Figueiredo", "Gouveia", "Magalhães",
        "Monteiro", "Palmeiro", "Quintela", "Teixeira",
    ]),
    "Brazil": (4, [
        "Caio", "Danilo", "Douglas", "Everton", "Felipe", "Gabriel", "Igor", "Lucas", "Matheus",
        "Murilo", "Renan", "Thiago", "Vinícius", "Wesley",
    ], [
        "Almeida", "Brandão", "Cavalcanti", "Damasceno", "Farias", "Guimarães", "Lacerda", "Macedo",
        "Nogueira", "Paiva", "Sampaio", "Toledo",
    ]),
    "Argentina": (3, [
        "Agustín", "Facundo", "Franco", "Gonzalo", "Joaquín", "Lisandro", "Leandro", "Matías",
        "Nahuel", "Tomás", "Valentín",
    ], [
        "Acosta", "Bustos", "Cabral", "Echagüe", "Ferreyra", "Giménez", "Ledesma", "Montiel",
        "Ocampo", "Sosa", "Villalba",
    ]),
    "Germany": (4, [
        "Felix", "Florian", "Jonas", "Julian", "Konstantin", "Leon", "Lukas", "Maximilian", "Niklas",
        "Timo", "Tobias",
    ], [
        "Bauer", "Brenner", "Engel", "Fuchs", "Hartmann", "Krüger", "Lindner", "Pohl",
        "Schreiber", "Vogel", "Winkler",
    ]),
    "Netherlands": (4, [
        "Bram", "Daan", "Jesper", "Joey", "Jelle", "Lars", "Luuk", "Milan", "Rik", "Sem",
        "Thijs",
    ], [
        "Bakker", "De Haas", "Dekker", "Hendriks", "Jansen", "Kuipers", "Mulder", "Smit", "Van Dalen",
        "Van der Linde", "Visser",
    ]),
    "Belgium": (3, [
        "Arthur", "Charles", "Dorian", "Jérémy", "Lander", "Louis", "Maxime", "Siebe", "Wout",
    ], [
        "Claes", "De Smet", "Goossens", "Janssens", "Lambert", "Maes", "Peeters", "Verbeke", "Wouters",
    ]),
    "Italy": (3, [
        "Alessandro", "Davide", "Federico", "Filippo", "Lorenzo", "Matteo", "Nicolò", "Riccardo",
        "Simone",
    ], [
        "Bellandi", "Caruso", "Esposito", "Ferraro", "Galli", "Lombardi", "Marchetti", "Rinaldi",
        "Santoro",
    ]),
    "Scandinavia": (5, [
        "Anders", "Emil", "Erik", "Isak", "Jesper", "Jonas", "Kasper", "Magnus", "Mathias", "Oskar",
        "Rasmus", "Sander",
    ], [
        "Andersen", "Berglund", "Dalgaard", "Ekdahl", "Halvorsen", "Holm", "Lindqvist", "Madsen",
        "Nyberg", "Sorensen", "Strand", "Vik",
    ]),
    "Ireland & Scotland": (5, [
        "Cian", "Conor", "Darragh", "Ewan", "Finn", "Fraser", "Callum", "Kieran", "Liam", "Niall",
        "Ross", "Seamus",
    ], [
        "Brannigan", "Corrigan", "Doherty", "Gallagher", "MacAulay", "McLennan", "McCann",
        "Murtagh", "Quinlan", "Rourke", "Sheridan", "Toner",
    ]),
    "West Africa": (6, [
        "Abdoulaye", "Amadou", "Cheikh", "Emeka", "Ibrahima", "Idrissa", "Kofi", "Kwame", "Mamadou",
        "Moussa", "Obinna", "Ousmane", "Sekou", "Taiwo", "Yaw", "Youssouf",
    ], [
        "Abara", "Adeyemi", "Asante", "Bakari", "Cissoko", "Danso", "Diallo", "Ekwueme", "Fofana",
        "Kouyaté", "Mensah", "Ndiaye", "Nwosu", "Okafor", "Oyelaran", "Sarr", "Traoré", "Yeboah",
    ]),
    "North Africa": (3, [
        "Amine", "Adel", "Bilal", "Hakim", "Ilyes", "Karim", "Nabil", "Omar", "Rachid",
        "Youssef",
    ], [
        "Belkacem", "Benali", "Bouzid", "El Amrani", "Haddad", "Mansouri", "Saidi", "Tahiri", "Zerrouki",
    ]),
    "Eastern Europe": (4, [
        "Andrej", "Bartosz", "Dominik", "Filip", "Jakub", "Luka", "Marko", "Mateusz", "Nikola",
        "Stefan",
    ], [
        "Babić", "Horvat", "Jović", "Kowalczyk", "Nowicki", "Petrović", "Wójcik",
        "Zieliński", "Marić",
    ]),
    "Japan & Korea": (2, [
        "Daichi", "Haruto", "Jae-won", "Kaoru", "Min-jun", "Ritsu", "Seung-ho", "Takumi", "Yuto",
    ], [
        "Fujita", "Hayashi", "Kang", "Matsuda", "Morita", "Ogawa", "Pyo", "Shin", "Yamada",
    ]),
    "USA": (2, [
        "Brenden", "Caden", "Christian", "Gio", "Jordan", "Tanner", "Tyler", "Wyatt",
    ], [
        "Adler", "Brockman", "Carver", "Delaney", "Harlan", "McKenna", "Sutter", "Wakefield",
    ]),
    "Colombia & Uruguay": (2, [
        "Andrés", "Camilo", "Diego", "Federico", "Jhon", "Mathías", "Santiago", "Yeison",
    ], [
        "Arango", "Bermúdez", "Cárdenas", "Larrañaga", "Mosquera", "Olivera",
        "Rentería", "Viera",
    ]),
}

MANAGER_FIRST = ["Alan", "Brendan", "Carlos", "Didier", "Erik", "Frank", "Gareth", "Hans", "Ivan",
                 "Javier", "Klaus", "Luis", "Marco", "Nils", "Owen", "Pieter", "Roberto", "Sean",
                 "Thomas", "Vincent"]
MANAGER_LAST = ["Abernathy", "Brauer", "Castellanos", "Delorme", "Eversley", "Fontaine", "Gutmann",
                "Haverford", "Iversen", "Jaramillo", "Kessler", "Lindgren", "Montague", "Norberg",
                "Okonkwo", "Penhaligon", "Quiroga", "Rademaker", "Stirling-Vane", "Thornbury"]

REFEREES = ["Alan Pryce", "Megan Holt", "Ravi Chandra", "Tomas Lindgren", "Grace Oduya",
            "Peter Kalb", "Sofia Marin", "Owen Treacher", "David Ashby", "Hannah Royle"]


# Concrete countries for each name pool (a player's nationality is one of these).
COUNTRIES = {
    "England": ["England"], "France": ["France"], "Spain": ["Spain"], "Portugal": ["Portugal"],
    "Brazil": ["Brazil"], "Argentina": ["Argentina"], "Germany": ["Germany", "Austria"],
    "Netherlands": ["Netherlands"], "Belgium": ["Belgium"], "Italy": ["Italy"],
    "Scandinavia": ["Denmark", "Norway", "Sweden"], "Ireland & Scotland": ["Republic of Ireland", "Scotland", "Northern Ireland"],
    "West Africa": ["Senegal", "Ghana", "Nigeria", "Ivory Coast", "Mali", "Guinea"],
    "North Africa": ["Morocco", "Algeria", "Tunisia", "Egypt"],
    "Eastern Europe": ["Poland", "Croatia", "Serbia", "Czech Republic"],
    "Japan & Korea": ["Japan", "South Korea"], "USA": ["United States"],
    "Colombia & Uruguay": ["Colombia", "Uruguay"],
}

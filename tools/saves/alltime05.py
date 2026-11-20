"""The all-time career leaders who had retired by the end of 2004, for League News's all-time lists: the record books
as they stood when MVP Baseball 2005 came out. Players still active in 2005 aren't here: their careers come from the
save (the real seasons and the dynasty's), so they climb these lists as the dynasty goes on.

Totals are the major leagues' (Baseball-Reference's career leaderboards, checked 2026-11; Willie Mays's are his
major-league numbers alone, as the books had them in 2005, without the 1948 Negro League season added since).
Keyed as news05's MILESTONES: the stat's label. Barry Bonds is here too, with his totals through 2004: he was still
playing, but isn't in MVP Baseball 2005, so his career would be missing from the lists otherwise.
"""

RETIRED = {
    "home runs": [
        ("Hank Aaron", 755), ("Babe Ruth", 714), ("Barry Bonds", 703), ("Willie Mays", 660), ("Frank Robinson", 586), ("Mark McGwire", 583),
        ("Harmon Killebrew", 573), ("Reggie Jackson", 563), ("Mike Schmidt", 548), ("Mickey Mantle", 536),
        ("Jimmie Foxx", 534), ("Willie McCovey", 521), ("Ted Williams", 521), ("Ernie Banks", 512),
        ("Eddie Mathews", 512), ("Mel Ott", 511), ("Eddie Murray", 504), ("Lou Gehrig", 493), ("Fred McGriff", 493),
        ("Stan Musial", 475), ("Willie Stargell", 475), ("Dave Winfield", 465), ("Jose Canseco", 462),
        ("Carl Yastrzemski", 452), ("Dave Kingman", 442), ("Andre Dawson", 438), ("Cal Ripken Jr.", 431),
        ("Billy Williams", 426), ("Darrell Evans", 414), ("Duke Snider", 407), ("Andres Galarraga", 399),
        ("Al Kaline", 399), ("Dale Murphy", 398), ("Joe Carter", 396), ("Graig Nettles", 390), ("Johnny Bench", 389),
        ("Dwight Evans", 385), ("Harold Baines", 384), ("Frank Howard", 382), ("Jim Rice", 382), ("Albert Belle", 381),
        ("Orlando Cepeda", 379), ("Tony Perez", 379), ("Matt Williams", 378), ("Norm Cash", 377),
        ("Carlton Fisk", 376), ("Rocky Colavito", 374), ("Gil Hodges", 370), ("Ralph Kiner", 369),
        ("Joe DiMaggio", 361), ("Gary Gaetti", 360), ("Johnny Mize", 359), ("Yogi Berra", 358),
        ("Greg Vaughn", 355), ("Lee May", 354)],
    "hits": [
        ("Pete Rose", 4256), ("Ty Cobb", 4189), ("Hank Aaron", 3771), ("Stan Musial", 3630), ("Tris Speaker", 3514),
        ("Cap Anson", 3435), ("Honus Wagner", 3420), ("Carl Yastrzemski", 3419), ("Paul Molitor", 3319),
        ("Eddie Collins", 3315), ("Willie Mays", 3283), ("Eddie Murray", 3255), ("Nap Lajoie", 3243),
        ("Cal Ripken Jr.", 3184), ("George Brett", 3154), ("Paul Waner", 3152), ("Robin Yount", 3142),
        ("Tony Gwynn", 3141), ("Dave Winfield", 3110), ("Rickey Henderson", 3055), ("Rod Carew", 3053),
        ("Lou Brock", 3023), ("Wade Boggs", 3010), ("Al Kaline", 3007), ("Roberto Clemente", 3000),
        ("Sam Rice", 2987), ("Sam Crawford", 2961), ("Frank Robinson", 2943), ("Jake Beckley", 2938),
        ("Willie Keeler", 2932), ("Rogers Hornsby", 2930), ("Al Simmons", 2927), ("Zack Wheat", 2884),
        ("Frankie Frisch", 2880), ("Mel Ott", 2876), ("Babe Ruth", 2873), ("Harold Baines", 2866),
        ("Jesse Burkett", 2850), ("Brooks Robinson", 2848), ("Charlie Gehringer", 2839), ("George Sisler", 2812),
        ("Barry Bonds", 2730), ("Andre Dawson", 2774), ("Vada Pinson", 2757), ("Luke Appling", 2749), ("Al Oliver", 2743),
        ("Goose Goslin", 2735), ("Tony Perez", 2732), ("Lou Gehrig", 2721), ("Rusty Staub", 2716),
        ("Bill Buckner", 2715), ("Dave Parker", 2712), ("Billy Williams", 2711), ("Doc Cramer", 2705)],
    "RBIs": [
        ("Hank Aaron", 2297), ("Babe Ruth", 2214), ("Lou Gehrig", 1995), ("Stan Musial", 1951), ("Ty Cobb", 1944),
        ("Jimmie Foxx", 1922), ("Eddie Murray", 1917), ("Willie Mays", 1903), ("Cap Anson", 1879), ("Mel Ott", 1860),
        ("Carl Yastrzemski", 1844), ("Barry Bonds", 1843), ("Ted Williams", 1839), ("Dave Winfield", 1833), ("Al Simmons", 1828),
        ("Frank Robinson", 1812), ("Honus Wagner", 1732), ("Reggie Jackson", 1702), ("Cal Ripken Jr.", 1695),
        ("Tony Perez", 1652), ("Ernie Banks", 1636), ("Harold Baines", 1628), ("Goose Goslin", 1612),
        ("Nap Lajoie", 1599), ("George Brett", 1596), ("Mike Schmidt", 1595), ("Andre Dawson", 1591),
        ("Rogers Hornsby", 1584), ("Harmon Killebrew", 1584), ("Al Kaline", 1582), ("Jake Beckley", 1581),
        ("Willie McCovey", 1555), ("Fred McGriff", 1550), ("Harry Heilmann", 1543), ("Willie Stargell", 1540),
        ("Joe DiMaggio", 1537), ("Tris Speaker", 1531), ("Sam Crawford", 1523), ("Mickey Mantle", 1509),
        ("Dave Parker", 1493), ("Billy Williams", 1475), ("Ed Delahanty", 1466), ("Rusty Staub", 1466),
        ("Eddie Mathews", 1453), ("Jim Rice", 1451), ("Joe Carter", 1445), ("George Davis", 1440),
        ("Yogi Berra", 1430), ("Charlie Gehringer", 1427), ("Andres Galarraga", 1425)],
    "stolen bases": [
        ("Rickey Henderson", 1406), ("Lou Brock", 938), ("Billy Hamilton", 914), ("Ty Cobb", 897),
        ("Tim Raines", 808), ("Vince Coleman", 752), ("Arlie Latham", 742), ("Eddie Collins", 741),
        ("Max Carey", 738), ("Honus Wagner", 723), ("Joe Morgan", 689), ("Willie Wilson", 668), ("Tom Brown", 658),
        ("Bert Campaneris", 649), ("Otis Nixon", 620), ("George Davis", 619), ("Billy Hoy", 596),
        ("Maury Wills", 586), ("George Van Haltren", 583), ("Ozzie Smith", 580), ("Hugh Duffy", 574),
        ("Bid McPhee", 568), ("Brett Butler", 558), ("Davey Lopes", 557), ("Cesar Cedeno", 550),
        ("Bill Dahlen", 548), ("John Ward", 540), ("Herman Long", 537), ("Patsy Donovan", 518), ("Jack Doyle", 518),
        ("Fred Clarke", 509), ("Harry Stovey", 509), ("Luis Aparicio", 506), ("Barry Bonds", 506), ("Paul Molitor", 504),
        ("Willie Keeler", 495), ("Clyde Milan", 495), ("Omar Moreno", 487), ("Roberto Alomar", 474),
        ("Mike Griffin", 473)],
    "wins": [
        ("Cy Young", 511), ("Walter Johnson", 417), ("Grover Alexander", 373), ("Christy Mathewson", 373),
        ("Pud Galvin", 365), ("Warren Spahn", 363), ("Kid Nichols", 362), ("Tim Keefe", 342), ("Steve Carlton", 329),
        ("John Clarkson", 328), ("Eddie Plank", 326), ("Nolan Ryan", 324), ("Don Sutton", 324), ("Phil Niekro", 318),
        ("Gaylord Perry", 314), ("Tom Seaver", 311), ("Old Hoss Radbourn", 310), ("Mickey Welch", 307),
        ("Lefty Grove", 300), ("Early Wynn", 300), ("Bobby Mathews", 297), ("Tommy John", 288),
        ("Bert Blyleven", 287), ("Robin Roberts", 286), ("Fergie Jenkins", 284), ("Tony Mullane", 284),
        ("Jim Kaat", 283), ("Red Ruffing", 273), ("Burleigh Grimes", 270), ("Jim Palmer", 268), ("Bob Feller", 266),
        ("Eppa Rixey", 266), ("Jim McCormick", 265), ("Gus Weyhing", 264), ("Ted Lyons", 260), ("Red Faber", 254),
        ("Jack Morris", 254), ("Carl Hubbell", 253), ("Bob Gibson", 251), ("Al Spalding", 251), ("Vic Willis", 249),
        ("Jack Quinn", 247), ("Joe McGinnity", 246), ("Amos Rusie", 246), ("Dennis Martinez", 245),
        ("Jack Powell", 245), ("Juan Marichal", 243), ("Herb Pennock", 241), ("Frank Tanana", 240),
        ("Mordecai Brown", 239)],
    "saves": [
        ("Lee Smith", 478), ("Dennis Eckersley", 390), ("Jeff Reardon", 367), ("Randy Myers", 347),
        ("Rollie Fingers", 341), ("John Wetteland", 330), ("Rick Aguilera", 318), ("Robb Nen", 314),
        ("Tom Henke", 311), ("Rich Gossage", 310), ("Jeff Montgomery", 304), ("Doug Jones", 303),
        ("Bruce Sutter", 300), ("Rod Beck", 286), ("Todd Worrell", 256), ("Dave Righetti", 252),
        ("Dan Quisenberry", 244), ("Sparky Lyle", 238), ("Hoyt Wilhelm", 228), ("Gene Garber", 218),
        ("Gregg Olson", 217)],
    "strikeouts": [
        ("Nolan Ryan", 5714), ("Steve Carlton", 4136), ("Bert Blyleven", 3701), ("Tom Seaver", 3640),
        ("Don Sutton", 3574), ("Gaylord Perry", 3534), ("Walter Johnson", 3508), ("Phil Niekro", 3342),
        ("Fergie Jenkins", 3192), ("Bob Gibson", 3117), ("Jim Bunning", 2855), ("Mickey Lolich", 2832),
        ("Cy Young", 2803), ("Frank Tanana", 2773), ("David Cone", 2668), ("Chuck Finley", 2610),
        ("Warren Spahn", 2583), ("Bob Feller", 2581), ("Tim Keefe", 2564), ("Jerry Koosman", 2556),
        ("Christy Mathewson", 2502), ("Don Drysdale", 2486), ("Jack Morris", 2478), ("Mark Langston", 2464),
        ("Jim Kaat", 2461), ("Sam McDowell", 2453), ("Luis Tiant", 2416), ("Dennis Eckersley", 2401),
        ("Sandy Koufax", 2396), ("Charlie Hough", 2362), ("Robin Roberts", 2357), ("Early Wynn", 2334),
        ("Rube Waddell", 2316), ("Juan Marichal", 2303), ("Dwight Gooden", 2293), ("Lefty Grove", 2266)],
}

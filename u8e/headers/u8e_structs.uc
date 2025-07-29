
/*
 *	Some structures for manipulation of the returns/parameters of some
 *	intrinsic functions.
 */

// Used in a few functions
struct Position2D {
	var x;
	var y;
}

// Return of get_object_position, and input of several other functions.
struct Position {
	var x;
	var y;
	var z;
}

// Used by find_nearby
struct FindSpec {
	struct<Position>;
	var quality;
	var framenum;
}

// Defined as return of one BG function and input of another.
struct PosObj {
	struct<Position>;
	var obj;
}

// Return of UI_click_on_item, and possible input of some other functions.
struct ObjPos {
	var obj;
	struct<Position>;
}




/*
 *	Coordinate axes - use when referencing X,Y,Z coordinate arrays.
 *	Note that the coordinates returned by UI_click_on_item are 1 array-index
 *	higher, because index 1 of the returned array is the actual item clicked on.
 *	You can resolve this to a regular X,Y,Z coordinates array by using
 *	array = removeFromArray(array, array[1]); (see also bg_externals.uc)
 */
//enum axes {
//	X = &struct<Position>::x,	//horizontal axis (numbered from west to east)
//	Y = &struct<Position>::y,	//vertical axis (numbered from north to south)
//	Z = &struct<Position>::z	//lift axis (numbered from ground to sky)
//};
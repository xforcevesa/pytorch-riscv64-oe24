// Copyright 2020 Google LLC
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include <stdint.h>

#include <xnnpack/common.h>


// Table of exp2(k / 2048) values decremented (as integer) by (k << 12), k = 0..2047
XNN_INTERNAL const uint32_t xnn_table_exp2minus_k_over_2048[2048] = {
  0x3F800000, 0x3F7FFB18, 0x3F7FF630, 0x3F7FF14A, 0x3F7FEC64, 0x3F7FE780, 0x3F7FE29C, 0x3F7FDDB9,
  0x3F7FD8D8, 0x3F7FD3F7, 0x3F7FCF17, 0x3F7FCA39, 0x3F7FC55B, 0x3F7FC07E, 0x3F7FBBA2, 0x3F7FB6C7,
  0x3F7FB1ED, 0x3F7FAD14, 0x3F7FA83C, 0x3F7FA365, 0x3F7F9E8F, 0x3F7F99BA, 0x3F7F94E6, 0x3F7F9013,
  0x3F7F8B41, 0x3F7F866F, 0x3F7F819F, 0x3F7F7CD0, 0x3F7F7802, 0x3F7F7334, 0x3F7F6E68, 0x3F7F699C,
  0x3F7F64D2, 0x3F7F6008, 0x3F7F5B40, 0x3F7F5678, 0x3F7F51B2, 0x3F7F4CEC, 0x3F7F4828, 0x3F7F4364,
  0x3F7F3EA1, 0x3F7F39E0, 0x3F7F351F, 0x3F7F305F, 0x3F7F2BA1, 0x3F7F26E3, 0x3F7F2226, 0x3F7F1D6A,
  0x3F7F18AF, 0x3F7F13F5, 0x3F7F0F3C, 0x3F7F0A85, 0x3F7F05CE, 0x3F7F0118, 0x3F7EFC63, 0x3F7EF7AF,
  0x3F7EF2FC, 0x3F7EEE4A, 0x3F7EE998, 0x3F7EE4E8, 0x3F7EE039, 0x3F7EDB8B, 0x3F7ED6DE, 0x3F7ED232,
  0x3F7ECD87, 0x3F7EC8DC, 0x3F7EC433, 0x3F7EBF8B, 0x3F7EBAE4, 0x3F7EB63D, 0x3F7EB198, 0x3F7EACF4,
  0x3F7EA850, 0x3F7EA3AE, 0x3F7E9F0D, 0x3F7E9A6C, 0x3F7E95CD, 0x3F7E912F, 0x3F7E8C91, 0x3F7E87F5,
  0x3F7E8359, 0x3F7E7EBF, 0x3F7E7A25, 0x3F7E758D, 0x3F7E70F5, 0x3F7E6C5F, 0x3F7E67C9, 0x3F7E6335,
  0x3F7E5EA1, 0x3F7E5A0F, 0x3F7E557D, 0x3F7E50ED, 0x3F7E4C5D, 0x3F7E47CF, 0x3F7E4341, 0x3F7E3EB4,
  0x3F7E3A29, 0x3F7E359E, 0x3F7E3115, 0x3F7E2C8C, 0x3F7E2804, 0x3F7E237E, 0x3F7E1EF8, 0x3F7E1A73,
  0x3F7E15F0, 0x3F7E116D, 0x3F7E0CEB, 0x3F7E086B, 0x3F7E03EB, 0x3F7DFF6C, 0x3F7DFAEF, 0x3F7DF672,
  0x3F7DF1F6, 0x3F7DED7C, 0x3F7DE902, 0x3F7DE489, 0x3F7DE012, 0x3F7DDB9B, 0x3F7DD725, 0x3F7DD2B1,
  0x3F7DCE3D, 0x3F7DC9CA, 0x3F7DC558, 0x3F7DC0E8, 0x3F7DBC78, 0x3F7DB809, 0x3F7DB39C, 0x3F7DAF2F,
  0x3F7DAAC3, 0x3F7DA659, 0x3F7DA1EF, 0x3F7D9D86, 0x3F7D991F, 0x3F7D94B8, 0x3F7D9052, 0x3F7D8BEE,
  0x3F7D878A, 0x3F7D8328, 0x3F7D7EC6, 0x3F7D7A65, 0x3F7D7606, 0x3F7D71A7, 0x3F7D6D4A, 0x3F7D68ED,
  0x3F7D6491, 0x3F7D6037, 0x3F7D5BDD, 0x3F7D5785, 0x3F7D532D, 0x3F7D4ED7, 0x3F7D4A81, 0x3F7D462D,
  0x3F7D41D9, 0x3F7D3D87, 0x3F7D3935, 0x3F7D34E5, 0x3F7D3095, 0x3F7D2C47, 0x3F7D27F9, 0x3F7D23AD,
  0x3F7D1F62, 0x3F7D1B17, 0x3F7D16CE, 0x3F7D1285, 0x3F7D0E3E, 0x3F7D09F8, 0x3F7D05B3, 0x3F7D016E,
  0x3F7CFD2B, 0x3F7CF8E9, 0x3F7CF4A8, 0x3F7CF067, 0x3F7CEC28, 0x3F7CE7EA, 0x3F7CE3AD, 0x3F7CDF71,
  0x3F7CDB35, 0x3F7CD6FB, 0x3F7CD2C2, 0x3F7CCE8A, 0x3F7CCA53, 0x3F7CC61D, 0x3F7CC1E8, 0x3F7CBDB4,
  0x3F7CB981, 0x3F7CB54F, 0x3F7CB11E, 0x3F7CACEF, 0x3F7CA8C0, 0x3F7CA492, 0x3F7CA065, 0x3F7C9C39,
  0x3F7C980F, 0x3F7C93E5, 0x3F7C8FBC, 0x3F7C8B94, 0x3F7C876E, 0x3F7C8348, 0x3F7C7F23, 0x3F7C7B00,
  0x3F7C76DD, 0x3F7C72BC, 0x3F7C6E9B, 0x3F7C6A7C, 0x3F7C665D, 0x3F7C6240, 0x3F7C5E24, 0x3F7C5A08,
  0x3F7C55EE, 0x3F7C51D5, 0x3F7C4DBC, 0x3F7C49A5, 0x3F7C458F, 0x3F7C417A, 0x3F7C3D66, 0x3F7C3953,
  0x3F7C3541, 0x3F7C3130, 0x3F7C2D20, 0x3F7C2911, 0x3F7C2503, 0x3F7C20F6, 0x3F7C1CEA, 0x3F7C18DF,
  0x3F7C14D5, 0x3F7C10CD, 0x3F7C0CC5, 0x3F7C08BE, 0x3F7C04B9, 0x3F7C00B4, 0x3F7BFCB1, 0x3F7BF8AE,
  0x3F7BF4AD, 0x3F7BF0AC, 0x3F7BECAD, 0x3F7BE8AE, 0x3F7BE4B1, 0x3F7BE0B5, 0x3F7BDCBA, 0x3F7BD8BF,
  0x3F7BD4C6, 0x3F7BD0CE, 0x3F7BCCD7, 0x3F7BC8E1, 0x3F7BC4EC, 0x3F7BC0F8, 0x3F7BBD05, 0x3F7BB913,
  0x3F7BB523, 0x3F7BB133, 0x3F7BAD44, 0x3F7BA957, 0x3F7BA56A, 0x3F7BA17E, 0x3F7B9D94, 0x3F7B99AA,
  0x3F7B95C2, 0x3F7B91DB, 0x3F7B8DF4, 0x3F7B8A0F, 0x3F7B862B, 0x3F7B8247, 0x3F7B7E65, 0x3F7B7A84,
  0x3F7B76A4, 0x3F7B72C5, 0x3F7B6EE7, 0x3F7B6B0A, 0x3F7B672F, 0x3F7B6354, 0x3F7B5F7A, 0x3F7B5BA1,
  0x3F7B57CA, 0x3F7B53F3, 0x3F7B501E, 0x3F7B4C49, 0x3F7B4876, 0x3F7B44A3, 0x3F7B40D2, 0x3F7B3D02,
  0x3F7B3933, 0x3F7B3565, 0x3F7B3198, 0x3F7B2DCC, 0x3F7B2A01, 0x3F7B2637, 0x3F7B226E, 0x3F7B1EA6,
  0x3F7B1ADF, 0x3F7B171A, 0x3F7B1355, 0x3F7B0F92, 0x3F7B0BCF, 0x3F7B080E, 0x3F7B044D, 0x3F7B008E,
  0x3F7AFCD0, 0x3F7AF913, 0x3F7AF556, 0x3F7AF19B, 0x3F7AEDE1, 0x3F7AEA29, 0x3F7AE671, 0x3F7AE2BA,
  0x3F7ADF04, 0x3F7ADB4F, 0x3F7AD79C, 0x3F7AD3E9, 0x3F7AD038, 0x3F7ACC87, 0x3F7AC8D8, 0x3F7AC52A,
  0x3F7AC17D, 0x3F7ABDD1, 0x3F7ABA25, 0x3F7AB67B, 0x3F7AB2D3, 0x3F7AAF2B, 0x3F7AAB84, 0x3F7AA7DE,
  0x3F7AA43A, 0x3F7AA096, 0x3F7A9CF3, 0x3F7A9952, 0x3F7A95B2, 0x3F7A9212, 0x3F7A8E74, 0x3F7A8AD7,
  0x3F7A873B, 0x3F7A83A0, 0x3F7A8006, 0x3F7A7C6D, 0x3F7A78D5, 0x3F7A753F, 0x3F7A71A9, 0x3F7A6E15,
  0x3F7A6A81, 0x3F7A66EF, 0x3F7A635D, 0x3F7A5FCD, 0x3F7A5C3E, 0x3F7A58B0, 0x3F7A5523, 0x3F7A5197,
  0x3F7A4E0C, 0x3F7A4A82, 0x3F7A46FA, 0x3F7A4372, 0x3F7A3FEC, 0x3F7A3C66, 0x3F7A38E2, 0x3F7A355E,
  0x3F7A31DC, 0x3F7A2E5B, 0x3F7A2ADB, 0x3F7A275C, 0x3F7A23DE, 0x3F7A2062, 0x3F7A1CE6, 0x3F7A196B,
  0x3F7A15F2, 0x3F7A1279, 0x3F7A0F02, 0x3F7A0B8C, 0x3F7A0816, 0x3F7A04A2, 0x3F7A012F, 0x3F79FDBD,
  0x3F79FA4D, 0x3F79F6DD, 0x3F79F36E, 0x3F79F001, 0x3F79EC94, 0x3F79E929, 0x3F79E5BE, 0x3F79E255,
  0x3F79DEED, 0x3F79DB86, 0x3F79D820, 0x3F79D4BB, 0x3F79D158, 0x3F79CDF5, 0x3F79CA93, 0x3F79C733,
  0x3F79C3D3, 0x3F79C075, 0x3F79BD18, 0x3F79B9BC, 0x3F79B661, 0x3F79B307, 0x3F79AFAE, 0x3F79AC56,
  0x3F79A900, 0x3F79A5AA, 0x3F79A256, 0x3F799F03, 0x3F799BB0, 0x3F79985F, 0x3F79950F, 0x3F7991C0,
  0x3F798E72, 0x3F798B26, 0x3F7987DA, 0x3F798490, 0x3F798146, 0x3F797DFE, 0x3F797AB7, 0x3F797771,
  0x3F79742C, 0x3F7970E8, 0x3F796DA5, 0x3F796A63, 0x3F796723, 0x3F7963E3, 0x3F7960A5, 0x3F795D67,
  0x3F795A2B, 0x3F7956F0, 0x3F7953B6, 0x3F79507D, 0x3F794D46, 0x3F794A0F, 0x3F7946D9, 0x3F7943A5,
  0x3F794072, 0x3F793D3F, 0x3F793A0E, 0x3F7936DE, 0x3F7933AF, 0x3F793082, 0x3F792D55, 0x3F792A29,
  0x3F7926FF, 0x3F7923D6, 0x3F7920AE, 0x3F791D86, 0x3F791A60, 0x3F79173C, 0x3F791418, 0x3F7910F5,
  0x3F790DD4, 0x3F790AB3, 0x3F790794, 0x3F790476, 0x3F790159, 0x3F78FE3D, 0x3F78FB22, 0x3F78F808,
  0x3F78F4F0, 0x3F78F1D8, 0x3F78EEC2, 0x3F78EBAD, 0x3F78E898, 0x3F78E585, 0x3F78E274, 0x3F78DF63,
  0x3F78DC53, 0x3F78D945, 0x3F78D637, 0x3F78D32B, 0x3F78D020, 0x3F78CD16, 0x3F78CA0D, 0x3F78C705,
  0x3F78C3FF, 0x3F78C0F9, 0x3F78BDF5, 0x3F78BAF1, 0x3F78B7EF, 0x3F78B4EE, 0x3F78B1EE, 0x3F78AEEF,
  0x3F78ABF2, 0x3F78A8F5, 0x3F78A5FA, 0x3F78A300, 0x3F78A006, 0x3F789D0E, 0x3F789A18, 0x3F789722,
  0x3F78942D, 0x3F78913A, 0x3F788E47, 0x3F788B56, 0x3F788866, 0x3F788577, 0x3F788289, 0x3F787F9D,
  0x3F787CB1, 0x3F7879C7, 0x3F7876DD, 0x3F7873F5, 0x3F78710E, 0x3F786E28, 0x3F786B43, 0x3F786860,
  0x3F78657D, 0x3F78629C, 0x3F785FBC, 0x3F785CDD, 0x3F7859FF, 0x3F785722, 0x3F785446, 0x3F78516C,
  0x3F784E92, 0x3F784BBA, 0x3F7848E3, 0x3F78460D, 0x3F784338, 0x3F784065, 0x3F783D92, 0x3F783AC1,
  0x3F7837F0, 0x3F783521, 0x3F783253, 0x3F782F86, 0x3F782CBB, 0x3F7829F0, 0x3F782727, 0x3F78245F,
  0x3F782197, 0x3F781ED1, 0x3F781C0D, 0x3F781949, 0x3F781686, 0x3F7813C5, 0x3F781105, 0x3F780E46,
  0x3F780B88, 0x3F7808CB, 0x3F78060F, 0x3F780355, 0x3F78009C, 0x3F77FDE3, 0x3F77FB2C, 0x3F77F877,
  0x3F77F5C2, 0x3F77F30E, 0x3F77F05C, 0x3F77EDAB, 0x3F77EAFA, 0x3F77E84C, 0x3F77E59E, 0x3F77E2F1,
  0x3F77E046, 0x3F77DD9B, 0x3F77DAF2, 0x3F77D84A, 0x3F77D5A3, 0x3F77D2FD, 0x3F77D059, 0x3F77CDB5,
  0x3F77CB13, 0x3F77C872, 0x3F77C5D2, 0x3F77C333, 0x3F77C096, 0x3F77BDF9, 0x3F77BB5E, 0x3F77B8C4,
  0x3F77B62B, 0x3F77B393, 0x3F77B0FD, 0x3F77AE67, 0x3F77ABD3, 0x3F77A940, 0x3F77A6AE, 0x3F77A41D,
  0x3F77A18D, 0x3F779EFF, 0x3F779C71, 0x3F7799E5, 0x3F77975A, 0x3F7794D0, 0x3F779248, 0x3F778FC0,
  0x3F778D3A, 0x3F778AB5, 0x3F778831, 0x3F7785AE, 0x3F77832C, 0x3F7780AC, 0x3F777E2C, 0x3F777BAE,
  0x3F777931, 0x3F7776B5, 0x3F77743B, 0x3F7771C1, 0x3F776F49, 0x3F776CD2, 0x3F776A5C, 0x3F7767E7,
  0x3F776573, 0x3F776301, 0x3F776090, 0x3F775E20, 0x3F775BB1, 0x3F775943, 0x3F7756D6, 0x3F77546B,
  0x3F775201, 0x3F774F98, 0x3F774D30, 0x3F774AC9, 0x3F774864, 0x3F774600, 0x3F77439C, 0x3F77413A,
  0x3F773EDA, 0x3F773C7A, 0x3F773A1C, 0x3F7737BE, 0x3F773562, 0x3F773308, 0x3F7730AE, 0x3F772E55,
  0x3F772BFE, 0x3F7729A8, 0x3F772753, 0x3F7724FF, 0x3F7722AD, 0x3F77205B, 0x3F771E0B, 0x3F771BBC,
  0x3F77196E, 0x3F771721, 0x3F7714D6, 0x3F77128C, 0x3F771043, 0x3F770DFB, 0x3F770BB4, 0x3F77096E,
  0x3F77072A, 0x3F7704E7, 0x3F7702A5, 0x3F770064, 0x3F76FE25, 0x3F76FBE6, 0x3F76F9A9, 0x3F76F76D,
  0x3F76F532, 0x3F76F2F9, 0x3F76F0C0, 0x3F76EE89, 0x3F76EC53, 0x3F76EA1E, 0x3F76E7EB, 0x3F76E5B8,
  0x3F76E387, 0x3F76E157, 0x3F76DF28, 0x3F76DCFA, 0x3F76DACE, 0x3F76D8A3, 0x3F76D679, 0x3F76D450,
  0x3F76D228, 0x3F76D002, 0x3F76CDDC, 0x3F76CBB8, 0x3F76C996, 0x3F76C774, 0x3F76C553, 0x3F76C334,
  0x3F76C116, 0x3F76BEF9, 0x3F76BCDE, 0x3F76BAC3, 0x3F76B8AA, 0x3F76B692, 0x3F76B47B, 0x3F76B265,
  0x3F76B051, 0x3F76AE3E, 0x3F76AC2C, 0x3F76AA1B, 0x3F76A80B, 0x3F76A5FD, 0x3F76A3F0, 0x3F76A1E4,
  0x3F769FD9, 0x3F769DD0, 0x3F769BC7, 0x3F7699C0, 0x3F7697BA, 0x3F7695B6, 0x3F7693B2, 0x3F7691B0,
  0x3F768FAF, 0x3F768DAF, 0x3F768BB0, 0x3F7689B3, 0x3F7687B7, 0x3F7685BC, 0x3F7683C2, 0x3F7681C9,
  0x3F767FD2, 0x3F767DDC, 0x3F767BE7, 0x3F7679F3, 0x3F767801, 0x3F76760F, 0x3F76741F, 0x3F767231,
  0x3F767043, 0x3F766E57, 0x3F766C6B, 0x3F766A82, 0x3F766899, 0x3F7666B1, 0x3F7664CB, 0x3F7662E6,
  0x3F766102, 0x3F765F1F, 0x3F765D3E, 0x3F765B5E, 0x3F76597F, 0x3F7657A1, 0x3F7655C5, 0x3F7653E9,
  0x3F76520F, 0x3F765037, 0x3F764E5F, 0x3F764C89, 0x3F764AB3, 0x3F7648E0, 0x3F76470D, 0x3F76453B,
  0x3F76436B, 0x3F76419C, 0x3F763FCE, 0x3F763E02, 0x3F763C37, 0x3F763A6D, 0x3F7638A4, 0x3F7636DC,
  0x3F763516, 0x3F763351, 0x3F76318D, 0x3F762FCA, 0x3F762E08, 0x3F762C48, 0x3F762A89, 0x3F7628CC,
  0x3F76270F, 0x3F762554, 0x3F76239A, 0x3F7621E1, 0x3F762029, 0x3F761E73, 0x3F761CBE, 0x3F761B0A,
  0x3F761958, 0x3F7617A6, 0x3F7615F6, 0x3F761447, 0x3F761299, 0x3F7610ED, 0x3F760F42, 0x3F760D98,
  0x3F760BEF, 0x3F760A48, 0x3F7608A2, 0x3F7606FD, 0x3F760559, 0x3F7603B7, 0x3F760215, 0x3F760075,
  0x3F75FED7, 0x3F75FD39, 0x3F75FB9D, 0x3F75FA02, 0x3F75F868, 0x3F75F6D0, 0x3F75F538, 0x3F75F3A2,
  0x3F75F20E, 0x3F75F07A, 0x3F75EEE8, 0x3F75ED57, 0x3F75EBC7, 0x3F75EA39, 0x3F75E8AC, 0x3F75E720,
  0x3F75E595, 0x3F75E40B, 0x3F75E283, 0x3F75E0FC, 0x3F75DF76, 0x3F75DDF2, 0x3F75DC6F, 0x3F75DAED,
  0x3F75D96C, 0x3F75D7ED, 0x3F75D66E, 0x3F75D4F1, 0x3F75D376, 0x3F75D1FB, 0x3F75D082, 0x3F75CF0A,
  0x3F75CD94, 0x3F75CC1E, 0x3F75CAAA, 0x3F75C937, 0x3F75C7C6, 0x3F75C655, 0x3F75C4E6, 0x3F75C379,
  0x3F75C20C, 0x3F75C0A1, 0x3F75BF37, 0x3F75BDCE, 0x3F75BC66, 0x3F75BB00, 0x3F75B99B, 0x3F75B838,
  0x3F75B6D5, 0x3F75B574, 0x3F75B414, 0x3F75B2B5, 0x3F75B158, 0x3F75AFFC, 0x3F75AEA1, 0x3F75AD48,
  0x3F75ABEF, 0x3F75AA98, 0x3F75A942, 0x3F75A7EE, 0x3F75A69B, 0x3F75A549, 0x3F75A3F8, 0x3F75A2A9,
  0x3F75A15B, 0x3F75A00E, 0x3F759EC2, 0x3F759D78, 0x3F759C2F, 0x3F759AE7, 0x3F7599A1, 0x3F75985C,
  0x3F759718, 0x3F7595D5, 0x3F759494, 0x3F759354, 0x3F759215, 0x3F7590D7, 0x3F758F9B, 0x3F758E60,
  0x3F758D26, 0x3F758BEE, 0x3F758AB7, 0x3F758981, 0x3F75884C, 0x3F758719, 0x3F7585E7, 0x3F7584B6,
  0x3F758387, 0x3F758259, 0x3F75812C, 0x3F758000, 0x3F757ED6, 0x3F757DAD, 0x3F757C85, 0x3F757B5F,
  0x3F757A3A, 0x3F757916, 0x3F7577F3, 0x3F7576D2, 0x3F7575B2, 0x3F757493, 0x3F757376, 0x3F75725A,
  0x3F75713F, 0x3F757025, 0x3F756F0D, 0x3F756DF6, 0x3F756CE0, 0x3F756BCC, 0x3F756AB9, 0x3F7569A7,
  0x3F756897, 0x3F756787, 0x3F75667A, 0x3F75656D, 0x3F756462, 0x3F756358, 0x3F75624F, 0x3F756147,
  0x3F756041, 0x3F755F3C, 0x3F755E39, 0x3F755D37, 0x3F755C36, 0x3F755B36, 0x3F755A38, 0x3F75593B,
  0x3F75583F, 0x3F755744, 0x3F75564B, 0x3F755553, 0x3F75545D, 0x3F755368, 0x3F755274, 0x3F755181,
  0x3F755090, 0x3F754FA0, 0x3F754EB1, 0x3F754DC4, 0x3F754CD8, 0x3F754BED, 0x3F754B03, 0x3F754A1B,
  0x3F754934, 0x3F75484F, 0x3F75476B, 0x3F754688, 0x3F7545A6, 0x3F7544C6, 0x3F7543E7, 0x3F754309,
  0x3F75422D, 0x3F754151, 0x3F754078, 0x3F753F9F, 0x3F753EC8, 0x3F753DF2, 0x3F753D1E, 0x3F753C4B,
  0x3F753B79, 0x3F753AA8, 0x3F7539D9, 0x3F75390B, 0x3F75383E, 0x3F753773, 0x3F7536A9, 0x3F7535E0,
  0x3F753519, 0x3F753453, 0x3F75338E, 0x3F7532CB, 0x3F753209, 0x3F753148, 0x3F753089, 0x3F752FCB,
  0x3F752F0E, 0x3F752E52, 0x3F752D98, 0x3F752CDF, 0x3F752C28, 0x3F752B72, 0x3F752ABD, 0x3F752A09,
  0x3F752957, 0x3F7528A6, 0x3F7527F7, 0x3F752749, 0x3F75269C, 0x3F7525F0, 0x3F752546, 0x3F75249D,
  0x3F7523F6, 0x3F75234F, 0x3F7522AA, 0x3F752207, 0x3F752165, 0x3F7520C4, 0x3F752024, 0x3F751F86,
  0x3F751EE9, 0x3F751E4D, 0x3F751DB3, 0x3F751D1A, 0x3F751C83, 0x3F751BEC, 0x3F751B57, 0x3F751AC4,
  0x3F751A32, 0x3F7519A1, 0x3F751911, 0x3F751883, 0x3F7517F6, 0x3F75176B, 0x3F7516E0, 0x3F751657,
  0x3F7515D0, 0x3F75154A, 0x3F7514C5, 0x3F751441, 0x3F7513BF, 0x3F75133E, 0x3F7512BF, 0x3F751241,
  0x3F7511C4, 0x3F751149, 0x3F7510CF, 0x3F751056, 0x3F750FDE, 0x3F750F68, 0x3F750EF4, 0x3F750E80,
  0x3F750E0E, 0x3F750D9E, 0x3F750D2E, 0x3F750CC0, 0x3F750C54, 0x3F750BE8, 0x3F750B7E, 0x3F750B16,
  0x3F750AAF, 0x3F750A49, 0x3F7509E4, 0x3F750981, 0x3F75091F, 0x3F7508BF, 0x3F750860, 0x3F750802,
  0x3F7507A6, 0x3F75074B, 0x3F7506F1, 0x3F750698, 0x3F750642, 0x3F7505EC, 0x3F750598, 0x3F750545,
  0x3F7504F3, 0x3F7504A3, 0x3F750454, 0x3F750407, 0x3F7503BB, 0x3F750370, 0x3F750327, 0x3F7502DE,
  0x3F750298, 0x3F750253, 0x3F75020F, 0x3F7501CC, 0x3F75018B, 0x3F75014B, 0x3F75010D, 0x3F7500CF,
  0x3F750094, 0x3F750059, 0x3F750020, 0x3F74FFE9, 0x3F74FFB2, 0x3F74FF7D, 0x3F74FF4A, 0x3F74FF18,
  0x3F74FEE7, 0x3F74FEB8, 0x3F74FE89, 0x3F74FE5D, 0x3F74FE31, 0x3F74FE07, 0x3F74FDDF, 0x3F74FDB8,
  0x3F74FD92, 0x3F74FD6D, 0x3F74FD4A, 0x3F74FD29, 0x3F74FD08, 0x3F74FCE9, 0x3F74FCCC, 0x3F74FCB0,
  0x3F74FC95, 0x3F74FC7B, 0x3F74FC63, 0x3F74FC4D, 0x3F74FC37, 0x3F74FC23, 0x3F74FC11, 0x3F74FC00,
  0x3F74FBF0, 0x3F74FBE1, 0x3F74FBD4, 0x3F74FBC9, 0x3F74FBBE, 0x3F74FBB6, 0x3F74FBAE, 0x3F74FBA8,
  0x3F74FBA3, 0x3F74FBA0, 0x3F74FB9E, 0x3F74FB9D, 0x3F74FB9E, 0x3F74FBA0, 0x3F74FBA4, 0x3F74FBA9,
  0x3F74FBAF, 0x3F74FBB7, 0x3F74FBC0, 0x3F74FBCB, 0x3F74FBD7, 0x3F74FBE4, 0x3F74FBF3, 0x3F74FC03,
  0x3F74FC14, 0x3F74FC27, 0x3F74FC3B, 0x3F74FC51, 0x3F74FC68, 0x3F74FC81, 0x3F74FC9A, 0x3F74FCB6,
  0x3F74FCD2, 0x3F74FCF0, 0x3F74FD10, 0x3F74FD31, 0x3F74FD53, 0x3F74FD76, 0x3F74FD9B, 0x3F74FDC2,
  0x3F74FDEA, 0x3F74FE13, 0x3F74FE3E, 0x3F74FE6A, 0x3F74FE97, 0x3F74FEC6, 0x3F74FEF6, 0x3F74FF28,
  0x3F74FF5B, 0x3F74FF8F, 0x3F74FFC5, 0x3F74FFFC, 0x3F750035, 0x3F75006F, 0x3F7500AA, 0x3F7500E7,
  0x3F750126, 0x3F750165, 0x3F7501A6, 0x3F7501E9, 0x3F75022D, 0x3F750272, 0x3F7502B9, 0x3F750301,
  0x3F75034A, 0x3F750395, 0x3F7503E2, 0x3F750430, 0x3F75047F, 0x3F7504CF, 0x3F750521, 0x3F750575,
  0x3F7505CA, 0x3F750620, 0x3F750678, 0x3F7506D1, 0x3F75072B, 0x3F750787, 0x3F7507E5, 0x3F750843,
  0x3F7508A4, 0x3F750905, 0x3F750968, 0x3F7509CD, 0x3F750A33, 0x3F750A9A, 0x3F750B03, 0x3F750B6D,
  0x3F750BD8, 0x3F750C45, 0x3F750CB4, 0x3F750D24, 0x3F750D95, 0x3F750E07, 0x3F750E7C, 0x3F750EF1,
  0x3F750F68, 0x3F750FE0, 0x3F75105A, 0x3F7510D5, 0x3F751152, 0x3F7511D0, 0x3F751250, 0x3F7512D1,
  0x3F751353, 0x3F7513D7, 0x3F75145C, 0x3F7514E3, 0x3F75156B, 0x3F7515F4, 0x3F75167F, 0x3F75170C,
  0x3F75179A, 0x3F751829, 0x3F7518BA, 0x3F75194C, 0x3F7519DF, 0x3F751A74, 0x3F751B0B, 0x3F751BA3,
  0x3F751C3C, 0x3F751CD7, 0x3F751D73, 0x3F751E11, 0x3F751EB0, 0x3F751F50, 0x3F751FF2, 0x3F752096,
  0x3F75213B, 0x3F7521E1, 0x3F752289, 0x3F752332, 0x3F7523DC, 0x3F752489, 0x3F752536, 0x3F7525E5,
  0x3F752695, 0x3F752747, 0x3F7527FB, 0x3F7528AF, 0x3F752966, 0x3F752A1D, 0x3F752AD6, 0x3F752B91,
  0x3F752C4D, 0x3F752D0A, 0x3F752DC9, 0x3F752E89, 0x3F752F4B, 0x3F75300F, 0x3F7530D3, 0x3F753199,
  0x3F753261, 0x3F75332A, 0x3F7533F5, 0x3F7534C1, 0x3F75358E, 0x3F75365D, 0x3F75372D, 0x3F7537FF,
  0x3F7538D2, 0x3F7539A7, 0x3F753A7D, 0x3F753B55, 0x3F753C2E, 0x3F753D08, 0x3F753DE4, 0x3F753EC2,
  0x3F753FA1, 0x3F754081, 0x3F754163, 0x3F754246, 0x3F75432B, 0x3F754411, 0x3F7544F9, 0x3F7545E2,
  0x3F7546CD, 0x3F7547B9, 0x3F7548A7, 0x3F754996, 0x3F754A86, 0x3F754B78, 0x3F754C6B, 0x3F754D60,
  0x3F754E57, 0x3F754F4F, 0x3F755048, 0x3F755143, 0x3F75523F, 0x3F75533D, 0x3F75543C, 0x3F75553D,
  0x3F75563F, 0x3F755742, 0x3F755848, 0x3F75594E, 0x3F755A56, 0x3F755B60, 0x3F755C6B, 0x3F755D77,
  0x3F755E85, 0x3F755F95, 0x3F7560A5, 0x3F7561B8, 0x3F7562CC, 0x3F7563E1, 0x3F7564F8, 0x3F756610,
  0x3F75672A, 0x3F756845, 0x3F756962, 0x3F756A80, 0x3F756BA0, 0x3F756CC1, 0x3F756DE4, 0x3F756F08,
  0x3F75702E, 0x3F757155, 0x3F75727E, 0x3F7573A8, 0x3F7574D3, 0x3F757600, 0x3F75772F, 0x3F75785F,
  0x3F757991, 0x3F757AC4, 0x3F757BF8, 0x3F757D2E, 0x3F757E66, 0x3F757F9F, 0x3F7580D9, 0x3F758215,
  0x3F758353, 0x3F758492, 0x3F7585D2, 0x3F758714, 0x3F758858, 0x3F75899D, 0x3F758AE3, 0x3F758C2B,
  0x3F758D75, 0x3F758EC0, 0x3F75900C, 0x3F75915A, 0x3F7592AA, 0x3F7593FB, 0x3F75954D, 0x3F7596A1,
  0x3F7597F7, 0x3F75994D, 0x3F759AA6, 0x3F759C00, 0x3F759D5B, 0x3F759EB8, 0x3F75A017, 0x3F75A177,
  0x3F75A2D8, 0x3F75A43B, 0x3F75A5A0, 0x3F75A706, 0x3F75A86D, 0x3F75A9D6, 0x3F75AB41, 0x3F75ACAD,
  0x3F75AE1B, 0x3F75AF8A, 0x3F75B0FA, 0x3F75B26C, 0x3F75B3E0, 0x3F75B555, 0x3F75B6CC, 0x3F75B844,
  0x3F75B9BE, 0x3F75BB39, 0x3F75BCB5, 0x3F75BE34, 0x3F75BFB3, 0x3F75C135, 0x3F75C2B7, 0x3F75C43C,
  0x3F75C5C1, 0x3F75C749, 0x3F75C8D1, 0x3F75CA5C, 0x3F75CBE8, 0x3F75CD75, 0x3F75CF04, 0x3F75D094,
  0x3F75D226, 0x3F75D3BA, 0x3F75D54F, 0x3F75D6E5, 0x3F75D87D, 0x3F75DA17, 0x3F75DBB2, 0x3F75DD4F,
  0x3F75DEED, 0x3F75E08C, 0x3F75E22E, 0x3F75E3D0, 0x3F75E575, 0x3F75E71A, 0x3F75E8C2, 0x3F75EA6B,
  0x3F75EC15, 0x3F75EDC1, 0x3F75EF6E, 0x3F75F11D, 0x3F75F2CE, 0x3F75F480, 0x3F75F633, 0x3F75F7E9,
  0x3F75F99F, 0x3F75FB57, 0x3F75FD11, 0x3F75FECC, 0x3F760089, 0x3F760247, 0x3F760407, 0x3F7605C9,
  0x3F76078C, 0x3F760950, 0x3F760B16, 0x3F760CDE, 0x3F760EA7, 0x3F761071, 0x3F76123D, 0x3F76140B,
  0x3F7615DA, 0x3F7617AB, 0x3F76197E, 0x3F761B51, 0x3F761D27, 0x3F761EFE, 0x3F7620D6, 0x3F7622B0,
  0x3F76248C, 0x3F762669, 0x3F762848, 0x3F762A28, 0x3F762C0A, 0x3F762DED, 0x3F762FD2, 0x3F7631B9,
  0x3F7633A1, 0x3F76358A, 0x3F763775, 0x3F763962, 0x3F763B50, 0x3F763D40, 0x3F763F31, 0x3F764124,
  0x3F764319, 0x3F76450F, 0x3F764706, 0x3F7648FF, 0x3F764AFA, 0x3F764CF6, 0x3F764EF4, 0x3F7650F4,
  0x3F7652F4, 0x3F7654F7, 0x3F7656FB, 0x3F765900, 0x3F765B08, 0x3F765D10, 0x3F765F1B, 0x3F766126,
  0x3F766334, 0x3F766543, 0x3F766753, 0x3F766965, 0x3F766B79, 0x3F766D8E, 0x3F766FA5, 0x3F7671BD,
  0x3F7673D7, 0x3F7675F3, 0x3F767810, 0x3F767A2F, 0x3F767C4F, 0x3F767E71, 0x3F768094, 0x3F7682B9,
  0x3F7684DF, 0x3F768707, 0x3F768931, 0x3F768B5C, 0x3F768D89, 0x3F768FB7, 0x3F7691E7, 0x3F769419,
  0x3F76964C, 0x3F769881, 0x3F769AB7, 0x3F769CEF, 0x3F769F28, 0x3F76A163, 0x3F76A3A0, 0x3F76A5DE,
  0x3F76A81E, 0x3F76AA5F, 0x3F76ACA2, 0x3F76AEE6, 0x3F76B12C, 0x3F76B374, 0x3F76B5BD, 0x3F76B808,
  0x3F76BA54, 0x3F76BCA2, 0x3F76BEF2, 0x3F76C143, 0x3F76C396, 0x3F76C5EA, 0x3F76C840, 0x3F76CA98,
  0x3F76CCF1, 0x3F76CF4B, 0x3F76D1A8, 0x3F76D405, 0x3F76D665, 0x3F76D8C6, 0x3F76DB29, 0x3F76DD8D,
  0x3F76DFF3, 0x3F76E25A, 0x3F76E4C3, 0x3F76E72E, 0x3F76E99A, 0x3F76EC08, 0x3F76EE77, 0x3F76F0E8,
  0x3F76F35B, 0x3F76F5CF, 0x3F76F845, 0x3F76FABC, 0x3F76FD35, 0x3F76FFB0, 0x3F77022C, 0x3F7704AA,
  0x3F770729, 0x3F7709AA, 0x3F770C2D, 0x3F770EB1, 0x3F771137, 0x3F7713BE, 0x3F771647, 0x3F7718D2,
  0x3F771B5E, 0x3F771DEC, 0x3F77207B, 0x3F77230C, 0x3F77259F, 0x3F772833, 0x3F772AC9, 0x3F772D61,
  0x3F772FFA, 0x3F773295, 0x3F773531, 0x3F7737CF, 0x3F773A6E, 0x3F773D10, 0x3F773FB2, 0x3F774257,
  0x3F7744FD, 0x3F7747A4, 0x3F774A4E, 0x3F774CF9, 0x3F774FA5, 0x3F775253, 0x3F775503, 0x3F7757B4,
  0x3F775A67, 0x3F775D1C, 0x3F775FD2, 0x3F77628A, 0x3F776543, 0x3F7767FE, 0x3F776ABB, 0x3F776D79,
  0x3F777039, 0x3F7772FB, 0x3F7775BE, 0x3F777883, 0x3F777B49, 0x3F777E11, 0x3F7780DB, 0x3F7783A6,
  0x3F778673, 0x3F778942, 0x3F778C12, 0x3F778EE4, 0x3F7791B8, 0x3F77948D, 0x3F779763, 0x3F779A3C,
  0x3F779D16, 0x3F779FF1, 0x3F77A2CF, 0x3F77A5AE, 0x3F77A88E, 0x3F77AB70, 0x3F77AE54, 0x3F77B13A,
  0x3F77B421, 0x3F77B709, 0x3F77B9F4, 0x3F77BCE0, 0x3F77BFCD, 0x3F77C2BD, 0x3F77C5AE, 0x3F77C8A0,
  0x3F77CB94, 0x3F77CE8A, 0x3F77D182, 0x3F77D47B, 0x3F77D776, 0x3F77DA72, 0x3F77DD70, 0x3F77E070,
  0x3F77E371, 0x3F77E674, 0x3F77E979, 0x3F77EC7F, 0x3F77EF87, 0x3F77F291, 0x3F77F59C, 0x3F77F8A9,
  0x3F77FBB8, 0x3F77FEC8, 0x3F7801DA, 0x3F7804ED, 0x3F780802, 0x3F780B19, 0x3F780E32, 0x3F78114C,
  0x3F781468, 0x3F781785, 0x3F781AA4, 0x3F781DC5, 0x3F7820E7, 0x3F78240B, 0x3F782731, 0x3F782A58,
  0x3F782D82, 0x3F7830AC, 0x3F7833D9, 0x3F783707, 0x3F783A36, 0x3F783D68, 0x3F78409B, 0x3F7843CF,
  0x3F784706, 0x3F784A3E, 0x3F784D77, 0x3F7850B3, 0x3F7853F0, 0x3F78572E, 0x3F785A6F, 0x3F785DB1,
  0x3F7860F5, 0x3F78643A, 0x3F786781, 0x3F786ACA, 0x3F786E14, 0x3F787160, 0x3F7874AE, 0x3F7877FD,
  0x3F787B4E, 0x3F787EA1, 0x3F7881F5, 0x3F78854B, 0x3F7888A3, 0x3F788BFD, 0x3F788F58, 0x3F7892B4,
  0x3F789613, 0x3F789973, 0x3F789CD5, 0x3F78A038, 0x3F78A39E, 0x3F78A704, 0x3F78AA6D, 0x3F78ADD7,
  0x3F78B143, 0x3F78B4B1, 0x3F78B820, 0x3F78BB91, 0x3F78BF03, 0x3F78C278, 0x3F78C5EE, 0x3F78C966,
  0x3F78CCDF, 0x3F78D05A, 0x3F78D3D7, 0x3F78D755, 0x3F78DAD5, 0x3F78DE57, 0x3F78E1DB, 0x3F78E560,
  0x3F78E8E7, 0x3F78EC6F, 0x3F78EFFA, 0x3F78F386, 0x3F78F713, 0x3F78FAA3, 0x3F78FE34, 0x3F7901C7,
  0x3F79055B, 0x3F7908F1, 0x3F790C89, 0x3F791023, 0x3F7913BE, 0x3F79175B, 0x3F791AF9, 0x3F791E9A,
  0x3F79223C, 0x3F7925E0, 0x3F792985, 0x3F792D2C, 0x3F7930D5, 0x3F793480, 0x3F79382C, 0x3F793BDA,
  0x3F793F89, 0x3F79433B, 0x3F7946EE, 0x3F794AA3, 0x3F794E59, 0x3F795211, 0x3F7955CB, 0x3F795987,
  0x3F795D44, 0x3F796103, 0x3F7964C4, 0x3F796887, 0x3F796C4B, 0x3F797011, 0x3F7973D8, 0x3F7977A2,
  0x3F797B6D, 0x3F797F39, 0x3F798308, 0x3F7986D8, 0x3F798AAA, 0x3F798E7E, 0x3F799253, 0x3F79962A,
  0x3F799A03, 0x3F799DDD, 0x3F79A1B9, 0x3F79A597, 0x3F79A977, 0x3F79AD58, 0x3F79B13C, 0x3F79B520,
  0x3F79B907, 0x3F79BCEF, 0x3F79C0D9, 0x3F79C4C5, 0x3F79C8B2, 0x3F79CCA2, 0x3F79D092, 0x3F79D485,
  0x3F79D879, 0x3F79DC70, 0x3F79E067, 0x3F79E461, 0x3F79E85C, 0x3F79EC59, 0x3F79F058, 0x3F79F458,
  0x3F79F85B, 0x3F79FC5F, 0x3F7A0064, 0x3F7A046C, 0x3F7A0875, 0x3F7A0C80, 0x3F7A108C, 0x3F7A149B,
  0x3F7A18AB, 0x3F7A1CBD, 0x3F7A20D0, 0x3F7A24E6, 0x3F7A28FD, 0x3F7A2D15, 0x3F7A3130, 0x3F7A354C,
  0x3F7A396A, 0x3F7A3D8A, 0x3F7A41AC, 0x3F7A45CF, 0x3F7A49F4, 0x3F7A4E1B, 0x3F7A5243, 0x3F7A566D,
  0x3F7A5A99, 0x3F7A5EC7, 0x3F7A62F7, 0x3F7A6728, 0x3F7A6B5B, 0x3F7A6F90, 0x3F7A73C6, 0x3F7A77FE,
  0x3F7A7C38, 0x3F7A8074, 0x3F7A84B1, 0x3F7A88F1, 0x3F7A8D32, 0x3F7A9175, 0x3F7A95B9, 0x3F7A99FF,
  0x3F7A9E47, 0x3F7AA291, 0x3F7AA6DD, 0x3F7AAB2A, 0x3F7AAF79, 0x3F7AB3CA, 0x3F7AB81C, 0x3F7ABC71,
  0x3F7AC0C7, 0x3F7AC51F, 0x3F7AC978, 0x3F7ACDD4, 0x3F7AD231, 0x3F7AD690, 0x3F7ADAF1, 0x3F7ADF53,
  0x3F7AE3B7, 0x3F7AE81D, 0x3F7AEC85, 0x3F7AF0EF, 0x3F7AF55A, 0x3F7AF9C7, 0x3F7AFE36, 0x3F7B02A6,
  0x3F7B0719, 0x3F7B0B8D, 0x3F7B1003, 0x3F7B147A, 0x3F7B18F4, 0x3F7B1D6F, 0x3F7B21EC, 0x3F7B266B,
  0x3F7B2AEC, 0x3F7B2F6E, 0x3F7B33F2, 0x3F7B3878, 0x3F7B3D00, 0x3F7B4189, 0x3F7B4614, 0x3F7B4AA1,
  0x3F7B4F30, 0x3F7B53C1, 0x3F7B5853, 0x3F7B5CE7, 0x3F7B617D, 0x3F7B6615, 0x3F7B6AAE, 0x3F7B6F4A,
  0x3F7B73E7, 0x3F7B7886, 0x3F7B7D26, 0x3F7B81C9, 0x3F7B866D, 0x3F7B8B13, 0x3F7B8FBB, 0x3F7B9464,
  0x3F7B9910, 0x3F7B9DBD, 0x3F7BA26C, 0x3F7BA71C, 0x3F7BABCF, 0x3F7BB083, 0x3F7BB539, 0x3F7BB9F1,
  0x3F7BBEAB, 0x3F7BC367, 0x3F7BC824, 0x3F7BCCE3, 0x3F7BD1A4, 0x3F7BD667, 0x3F7BDB2B, 0x3F7BDFF2,
  0x3F7BE4BA, 0x3F7BE984, 0x3F7BEE4F, 0x3F7BF31D, 0x3F7BF7EC, 0x3F7BFCBD, 0x3F7C0190, 0x3F7C0665,
  0x3F7C0B3B, 0x3F7C1014, 0x3F7C14EE, 0x3F7C19CA, 0x3F7C1EA8, 0x3F7C2387, 0x3F7C2868, 0x3F7C2D4C,
  0x3F7C3231, 0x3F7C3717, 0x3F7C3C00, 0x3F7C40EB, 0x3F7C45D7, 0x3F7C4AC5, 0x3F7C4FB5, 0x3F7C54A6,
  0x3F7C599A, 0x3F7C5E8F, 0x3F7C6386, 0x3F7C687F, 0x3F7C6D7A, 0x3F7C7277, 0x3F7C7775, 0x3F7C7C75,
  0x3F7C8177, 0x3F7C867B, 0x3F7C8B81, 0x3F7C9088, 0x3F7C9592, 0x3F7C9A9D, 0x3F7C9FAA, 0x3F7CA4B9,
  0x3F7CA9C9, 0x3F7CAEDC, 0x3F7CB3F0, 0x3F7CB906, 0x3F7CBE1E, 0x3F7CC338, 0x3F7CC853, 0x3F7CCD71,
  0x3F7CD290, 0x3F7CD7B1, 0x3F7CDCD4, 0x3F7CE1F9, 0x3F7CE71F, 0x3F7CEC48, 0x3F7CF172, 0x3F7CF69E,
  0x3F7CFBCC, 0x3F7D00FB, 0x3F7D062D, 0x3F7D0B60, 0x3F7D1096, 0x3F7D15CD, 0x3F7D1B06, 0x3F7D2040,
  0x3F7D257D, 0x3F7D2ABC, 0x3F7D2FFC, 0x3F7D353E, 0x3F7D3A82, 0x3F7D3FC8, 0x3F7D450F, 0x3F7D4A59,
  0x3F7D4FA4, 0x3F7D54F1, 0x3F7D5A40, 0x3F7D5F91, 0x3F7D64E4, 0x3F7D6A39, 0x3F7D6F8F, 0x3F7D74E7,
  0x3F7D7A41, 0x3F7D7F9D, 0x3F7D84FB, 0x3F7D8A5B, 0x3F7D8FBC, 0x3F7D9520, 0x3F7D9A85, 0x3F7D9FEC,
  0x3F7DA555, 0x3F7DAAC0, 0x3F7DB02D, 0x3F7DB59B, 0x3F7DBB0B, 0x3F7DC07E, 0x3F7DC5F2, 0x3F7DCB68,
  0x3F7DD0DF, 0x3F7DD659, 0x3F7DDBD5, 0x3F7DE152, 0x3F7DE6D1, 0x3F7DEC52, 0x3F7DF1D5, 0x3F7DF75A,
  0x3F7DFCE1, 0x3F7E0269, 0x3F7E07F4, 0x3F7E0D80, 0x3F7E130E, 0x3F7E189E, 0x3F7E1E30, 0x3F7E23C4,
  0x3F7E295A, 0x3F7E2EF1, 0x3F7E348B, 0x3F7E3A26, 0x3F7E3FC3, 0x3F7E4562, 0x3F7E4B03, 0x3F7E50A6,
  0x3F7E564A, 0x3F7E5BF1, 0x3F7E6199, 0x3F7E6743, 0x3F7E6CF0, 0x3F7E729E, 0x3F7E784D, 0x3F7E7DFF,
  0x3F7E83B3, 0x3F7E8968, 0x3F7E8F20, 0x3F7E94D9, 0x3F7E9A94, 0x3F7EA051, 0x3F7EA610, 0x3F7EABD1,
  0x3F7EB194, 0x3F7EB758, 0x3F7EBD1F, 0x3F7EC2E7, 0x3F7EC8B2, 0x3F7ECE7E, 0x3F7ED44C, 0x3F7EDA1C,
  0x3F7EDFED, 0x3F7EE5C1, 0x3F7EEB97, 0x3F7EF16E, 0x3F7EF748, 0x3F7EFD23, 0x3F7F0300, 0x3F7F08DF,
  0x3F7F0EC0, 0x3F7F14A3, 0x3F7F1A88, 0x3F7F206E, 0x3F7F2657, 0x3F7F2C41, 0x3F7F322E, 0x3F7F381C,
  0x3F7F3E0C, 0x3F7F43FE, 0x3F7F49F2, 0x3F7F4FE8, 0x3F7F55E0, 0x3F7F5BD9, 0x3F7F61D5, 0x3F7F67D2,
  0x3F7F6DD2, 0x3F7F73D3, 0x3F7F79D6, 0x3F7F7FDB, 0x3F7F85E2, 0x3F7F8BEB, 0x3F7F91F6, 0x3F7F9803,
  0x3F7F9E11, 0x3F7FA422, 0x3F7FAA34, 0x3F7FB049, 0x3F7FB65F, 0x3F7FBC77, 0x3F7FC291, 0x3F7FC8AD,
  0x3F7FCECB, 0x3F7FD4EB, 0x3F7FDB0D, 0x3F7FE131, 0x3F7FE756, 0x3F7FED7E, 0x3F7FF3A7, 0x3F7FF9D3,
};

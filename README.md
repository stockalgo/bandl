<p align="center"><a href="http://bandl.io" ><img src="https://raw.githubusercontent.com/stockalgo/bandl/master/logo.svg"></a> </p>

bandl is open source library, provides apis for equity stock, derivatives, commodities, and cryptocurrencies.

## Installation

Use the package manager [pip](https://pip.pypa.io/en/stable/) to install bandl.

```bash
pip install bandl
```

<!-- @import "[TOC]" {cmd="toc" depthFrom=1 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [Installation](#installation)
- [Usage](#usage)
  - [To import NSE Data Module](#to-import-nse-data-module)
    - [To get Option chain data from New NSE website](#to-get-option-chain-data-from-new-nse-website)
    - [To get Option chain data](#to-get-option-chain-data)
    - [To get stock historical data.](#to-get-stock-historical-data)
    - [To get FII/DII data.](#to-get-fiidii-data)
- [Contributing](#contributing)
- [License](#license)

<!-- /code_chunk_output -->


## Usage

### To import NSE Data Module
```python
from bandl.nse_data import NseData
nd = NseData() # returns 'NseData object'. can be use to get nse data.
```
#### To get Option chain data from New NSE website
```python
strikes = nd.get_oc_strike_prices("NIFTY")
oc_data = nd.get_option_data("NIFTY",strikes=strikes)
```

#### To get Option chain data
```python
expiry_dates = nd.get_oc_exp_dates(symbol) #return available expiry dates
nd.get_option_chain_excel(symbol,expiry_date,filepath) #dumps option chain to file_path
# or get in pandas dateframe
bn_df = nd.get_option_chain_df(symbol, expiry_date,dayfirst=False) #returns option chain in pandas data frame.
```
#### To get stock historical data.
```python
data_frame = nd.get_data(symbol,series="EQ",start=None,end=None,periods=None,dayfirst=False) #returns historical data in pandas data frames
```

#### To get FII/DII data.
```python
part_oi_df = nd.get_part_oi_df(start=None,end=None,periods=None,dayfirst=False,workers=None)
```

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Kindly follow PEP 8 Coding Style guidelines. Refer: https://www.python.org/dev/peps/pep-0008/

Please make sure to update tests as appropriate.

## License
[MIT](https://choosealicense.com/licenses/mit/)

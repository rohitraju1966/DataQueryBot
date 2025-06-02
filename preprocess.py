import os
import re
import pandas as pd
from glob import glob
import sqlite3


class DataPreprocessor:
    def __init__(self, input_folder="Raw", output_folder="Processed"):
        self.input_folder = input_folder
        self.output_folder = output_folder
        os.makedirs(self.output_folder, exist_ok=True)

        self.orders_json_cols = ["delivery_info", "subscription_discounts_metadata"]
        self.stores_json_cols = ["platform_fee", "delivery_fee", "pre_sale", "consumer_fee"]
        self.customers_json_cols = []

    # Replace commas inside nested JSON-like {...} structures with semicolons
    def replace_commas_in_json_fields(self, line: str) -> str:
        output = ""
        buffer = ""
        stack = 0
        inside_json = False

        for ch in line:
            if ch == '{':
                stack += 1
                inside_json = True
                buffer += ch
            elif ch == '}':
                stack -= 1
                buffer += ch
                if stack == 0:
                    inside_json = False
                    output += buffer.replace(",", ";")
                    buffer = ""
            elif inside_json:
                buffer += ch
            else:
                output += ch

        output += buffer
        return output

    # Preprocess all CSV files by replacing problematic commas and saving them
    def preprocess_files(self):
        all_csvs = glob(os.path.join(self.input_folder, "*.csv"))
        for csv_file in all_csvs:
            file_name = os.path.basename(csv_file)
            output_path = os.path.join(self.output_folder, f"fixed_{file_name}")

            with open(csv_file, "r", encoding="utf-8") as infile, \
                 open(output_path, "w", encoding="utf-8") as outfile:

                for line in infile:
                    fixed_line = self.replace_commas_in_json_fields(line)
                    outfile.write(fixed_line)

            print(f"Processed: {file_name} → {output_path}")

    # Load cleaned CSVs, restore commas, and apply final cleanup and imputation
    def clean_and_save_all(self):
        fixed_folder = self.output_folder
        def load_and_restore_commas(files, json_columns):
            dfs = []
            for file in files:
                try:
                    df = pd.read_csv(file, dtype=str)
                    for col in json_columns:
                        if col in df.columns:
                            df[col] = df[col].str.replace(";", ",", regex=False)
                    dfs.append(df)
                except Exception as e:
                    print(f"Error reading {file}: {e}")
            if dfs:
                return pd.concat(dfs, ignore_index=True).drop_duplicates()
            return pd.DataFrame()

        orders_files = glob(os.path.join(self.output_folder, "fixed_orders_*.csv"))
        customers_files = glob(os.path.join(self.output_folder, "fixed_customers_*.csv"))
        stores_files = glob(os.path.join(self.output_folder, "fixed_stores_*.csv")) + \
                       [os.path.join(self.output_folder, "fixed_stores.csv")]

        orders_df = load_and_restore_commas(orders_files, self.orders_json_cols)
        customers_df = load_and_restore_commas(customers_files, self.customers_json_cols)
        stores_df = load_and_restore_commas(stores_files, self.stores_json_cols)

        if 'delivery_fee_in_cents' in orders_df.columns:
            orders_df.loc[
                (
                    orders_df['fulfillment_type'].isin(['pickup', 'curbside']) |
                    orders_df['order_type'].isin(['store_credit_reload', 'gift_card', 'subscription_purchase'])
                ) & orders_df['delivery_fee_in_cents'].isna(),
                'delivery_fee_in_cents'
            ] = 0

        orders_df['subscription_discounts_metadata'] = orders_df['subscription_discounts_metadata'].fillna('{}')
        orders_df['delivery_info'] = orders_df['delivery_info'].fillna('{}')
        orders_df['notes'] = orders_df['notes'].fillna('')
        orders_df['scheduled_fulfillment_at'] = orders_df['scheduled_fulfillment_at'].fillna(orders_df['created_at'])

        stores_df['platform_fee'] = stores_df['platform_fee'].fillna('{}')
        stores_df['consumer_fee'] = stores_df['consumer_fee'].fillna('{}')

        orders_df.to_csv(os.path.join(self.output_folder, "cleaned_orders.csv"), index=False)
        customers_df.to_csv(os.path.join(self.output_folder, "cleaned_customers.csv"), index=False)
        stores_df.to_csv(os.path.join(self.output_folder, "cleaned_stores.csv"), index=False)

        print("All cleaned files saved successfully!")
        
        db_path = os.path.join(fixed_folder, "dashboard_chatbot.db")
        conn = sqlite3.connect(db_path)
        orders_df.to_sql("orders", conn, if_exists="replace", index=False)
        customers_df.to_sql("customers", conn, if_exists="replace", index=False)
        stores_df.to_sql("stores", conn, if_exists="replace", index=False)
        conn.close()

        print(f"Loaded all tables into SQLite DB at {db_path}")


# Run preprocessing when script is executed directly
if __name__ == "__main__":
    processor = DataPreprocessor()
    processor.preprocess_files()
    processor.clean_and_save_all()

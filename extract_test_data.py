import os
import csv
import random


def main():
    input_folder = "data/input"
    output_folder = "data/test_sample"
    target_count = 50

    if not os.path.exists(input_folder):
        print(f"Error: {input_folder} directory does not exist.")
        return

    os.makedirs(output_folder, exist_ok=True)

    # Scan for CSV files
    csv_files = sorted([f for f in os.listdir(input_folder) if f.lower().endswith('.csv')])
    if not csv_files:
        print("No CSV files found in input/.")
        return

    # To store: headers for each file, and list of (filename, row) for valid data rows
    headers = {}
    all_valid_rows = []

    for fname in csv_files:
        fpath = os.path.join(input_folder, fname)
        try:
            with open(fpath, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                try:
                    header = next(reader)
                    headers[fname] = header
                except StopIteration:
                    continue

                # We need to detect where the title column is to ensure we sample valid records
                # (matching the logic in detect_headers in export_to_sheets.py)
                title_col_idx = 0
                for i, col in enumerate(header):
                    col_clean = col.strip().lower()
                    if col_clean in ['title', '標題', '名稱', 'name']:
                        title_col_idx = i
                        break

                for row in reader:
                    if not row or len(row) <= title_col_idx:
                        continue
                    # Check if the title is non-empty
                    title = row[title_col_idx].strip()
                    if title:
                        all_valid_rows.append((fname, row))
        except Exception as e:
            print(f"Error reading {fname}: {e}")

    print(f"Total valid records found: {len(all_valid_rows)}")

    # Sample exactly target_count records (or less if total is less than target_count)
    random.seed(42)  # For reproducibility
    sample_size = min(target_count, len(all_valid_rows))
    sampled_records = random.sample(all_valid_rows, sample_size)

    # Group sampled rows by filename
    sampled_by_file = {fname: [] for fname in csv_files}
    for fname, row in sampled_records:
        sampled_by_file[fname].append(row)

    # Write the output files into input_test/
    written_files = 0
    written_records = 0
    for fname in csv_files:
        rows_to_write = sampled_by_file[fname]
        # Only write files that have at least one record (or headers if desired)
        # We write all files (even empty ones with just headers) to preserve the list names structure
        out_path = os.path.join(output_folder, fname)
        try:
            with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(headers[fname])
                for row in rows_to_write:
                    writer.writerow(row)
            written_files += 1
            written_records += len(rows_to_write)
        except Exception as e:
            print(f"Error writing {fname} to {output_folder}: {e}")

    print(f"Extraction complete. Sampled {written_records} records across "
          f"{written_files} files into '{output_folder}/'.")


if __name__ == '__main__':
    main()

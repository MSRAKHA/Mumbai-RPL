import gradio as gr
import pandas as pd
import os
import json
import base64
from PIL import Image
from groq import Groq
from langchain.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing import List, Optional
import io

# 🔹 *Configuration*
GROQ_API_KEY = "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"  # Replace with your actual API key
OUTPUT_EXCEL = "invoices.xlsx"

# 🔹 *Initialize Groq Client*
client = Groq(api_key=GROQ_API_KEY)

# 🔹 *Pydantic Model*
class InvoiceData(BaseModel):
    doc_type: Optional[str] = None
    bill_number: Optional[str] = None
    date: Optional[str] = None
    vendor_name: Optional[str] = None
    line_items: List[dict] = []
    discount: Optional[float] = None
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    total: Optional[float] = None
    dtl_signature: Optional[bool] = None
    fo_signature: Optional[bool] = None
    description_present: Optional[bool] = None
    image_name: Optional[str] = None

# 🔹 *LangChain Prompt*
PROMPT_TEMPLATE = """
You are an expert Multilingual invoice parser. Extract structured details from the OCR text below:

### OCR Text (Extracted from Image)
{ocr_text}

### **Extract the following fields**:
- doc_type: Type of document (cash bill, invoice, receipt).**always return as (string)**
- bill_number: Bill/invoice/receipt number, usually preceded by terms like "Bill No.", "No.", "क्र.", "बी.नं.".**always return as (string)**
- date: Bill date, usually in `DD-MM-YYYY` or `DD/MM/YYYY` format, with prefixes like "Date", "दिनांक", "तारीख".**always return as (string)**
- vendor_name: Shop/vendor name, which may appear under "Shop Name", "Retailer", "व्यवसाय का नाम".**always return as (string)**
- line_items: List of items with description("Description","Item Name", "Particulars", "विवरण", "वस्तु का नाम"), quantity("Qty", "Quantity", "संख्या", "मात्रा"), price("Rate", "Price", "Unit Price", "दर", "कीमत"), and amount("Total", "Amount", "राशि", "कुल राशि").**always return as (dict)**
- discount: Any discount amount, **always return as a number (float), without currency symbols**.
- cgst: Central GST amount, **always return as a number (float), without currency symbols**.
- sgst: State GST amount, **always return as a number (float), without currency symbols**.
- total: Final bill total, **always return as a number (float), without currency symbols**.
- dtl_signature: True if a District Team Lead signature is present.
- fo_signature: True if a Field Officer signature is present.
- description_present: True if extra description exists below the bill.

### **Output JSON Format**
{{
{format_instructions}
}}
"""



# 🔹 *Helper Functions*
def encode_image_to_base64(image):
    with open(image, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def extract_text_from_image(image):
    """Extracts text from image using Groq LLaMA Vision."""
    image_base64 = encode_image_to_base64(image)
    completion = client.chat.completions.create(
        model="llama-3.2-90b-vision-preview",
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": "Extract all text from this image. Return only the extracted text in JSON."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
            ]},
        ],
        temperature=0.1,
        max_completion_tokens=1024,
        top_p=1
    )
    return completion.choices[0].message.content

def process_invoice(image_path):
    """Extracts text, structures it into JSON, and validates via Pydantic."""
    extracted_text = extract_text_from_image(image_path)

    final_prompt = PROMPT_TEMPLATE.format(ocr_text=extracted_text, format_instructions="Return a valid JSON without additional formatting text or code block markers.")

    completion = client.chat.completions.create(
        model="llama-3.2-90b-vision-preview",
        messages=[{"role": "user", "content": final_prompt}],
        temperature=0.1,
        max_tokens=1024,
        top_p=1,
    )

    response_content = completion.choices[0].message.content.strip()

    # Validate JSON response
    try:
        raw_data = json.loads(response_content)
        structured_data = InvoiceData(**raw_data).dict()
    except (json.JSONDecodeError, Exception) as e:
        return {"error": f"Error parsing JSON: {e}"}

    return structured_data


def update_excel(doc_type, bill_number, date, vendor_name, discount, cgst, sgst, total, line_items_df, dtl_signature, fo_signature, description_present):
    try:
        OUTPUT_EXCEL = "invoices.xlsx"

        #convert checkbox value to "Yes"/"No"
        dtl_signature = "Yes" if dtl_signature else "No"
        fo_signature = "Yes" if fo_signature else "No"
        description_present = "Yes" if description_present else "No"

        # 🔹 Convert `line_items_table` from Gradio format to Pandas DataFrame
        if isinstance(line_items_df, list):
            line_items_df = pd.DataFrame(line_items_df, columns=["Description", "Quantity", "Price", "Amount"])
        elif not isinstance(line_items_df, pd.DataFrame):
            line_items_df = pd.DataFrame(columns=["Description", "Quantity", "Price", "Amount"])  # Empty DataFrame

        #read existing excel to determine next S.No
        if os.path.exists(OUTPUT_EXCEL):
            existing_df = pd.read_excel(OUTPUT_EXCEL, engine="openpyxl")
            last_s_no = existing_df["S.no"].dropna().astype(int).max()+1
        else:
            last_s_no = 1

        # Convert DataFrame to list of lists
        line_items = line_items_df.values.tolist()

        columns = ["S.no", "doc_type", "bill_number", "date", "vendor_name", "description", "quantity", "price", "amount", "discount", "cgst", "sgst", "total","dtl_signature","fo_signature","description_present"]
        expanded_rows = []

        for idx,item in enumerate(line_items):
            expanded_rows.append({
                "S.no": last_s_no if idx ==0  else "",
                "doc_type": doc_type if idx == 0 else "",
                "bill_number": bill_number if idx ==0 else "",
                "date": date if idx ==0 else "",
                "vendor_name": vendor_name if idx ==0 else "",
                "description": item[0] if len(item) > 0 else "",  # Description
                "quantity": item[1] if len(item) > 1 else 0,      # Quantity
                "price": item[2] if len(item) > 2 else 0,         # Price
                "amount": item[-1] if len(item) > 3 else 0,  #  Amount
                "discount": discount if idx ==0 else "",
                "cgst": cgst if idx ==0 else "",
                "sgst": sgst if idx ==0 else "",
                "total": total if idx ==0 else "",
                "dtl_signature": dtl_signature if idx ==0 else "",
                "fo_signature": fo_signature if idx ==0 else "",
                "description_present": description_present if idx ==0 else ""
            })

        df = pd.DataFrame(expanded_rows)

        # Append to existing Excel file
        if os.path.exists(OUTPUT_EXCEL):
            existing_df = pd.read_excel(OUTPUT_EXCEL, engine="openpyxl")
            df_final = pd.concat([existing_df, df], ignore_index=True)
        else:
            df_final = df

        df_final.to_excel(OUTPUT_EXCEL, index=False, engine="openpyxl")

        return "Data successfully updated in Excel!", OUTPUT_EXCEL  # Return the file path for download

    except Exception as e:
        return f"Error: {str(e)}", None


# Function to reset the image to its original size
def reset_image(image):
    return image

# Function to zoom in the image
def zoom_in(image):
    width, height = image.size
    return image.resize((int(width * 1.2), int(height * 1.2)))

# Function to zoom out the image
def zoom_out(image):
    width, height = image.size
    return image.resize((int(width * 0.8), int(height * 0.8)))

def calculate_total_amount(line_items):
    """Calculate total amount for each line item."""
    for item in line_items:
        if len(item) >= 3:
            try:
                quantity = float(item[1])
                price = float(item[2])
                item[3] = quantity * price
            except ValueError:
                item[3] = 0.0  # Default to 0 if conversion fails
    return line_items

# 🔹 *Gradio UI*
with gr.Blocks(theme=gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="indigo",
)) as demo:
    gr.Markdown(
        """
        <div style="text-align: center; padding: 20px;">
            <h1 style="color: #1F4298; font-size: 2.0em; margin-bottom: 10px;">📄 Invoicify</h1>
        </div>
        """
    )
    
    with gr.Row():
        with gr.Column(scale=3):
            # Enhanced image input with zoom capabilities
            image_input = gr.Image(
                type="pil",
                label="Upload Invoice",
                interactive=True,
                height=700
            )
            
            # Add zoom in, zoom out, and reset buttons
            with gr.Row():
                zoom_in_btn = gr.Button("🔍 Zoom In", variant="secondary")
                zoom_out_btn = gr.Button("🔍 Zoom Out", variant="secondary")
                reset_view_btn = gr.Button("↺ Reset View", variant="secondary")

                

        with gr.Column(scale=3):
            with gr.Column():
                gr.Markdown("<h3 style='color: #1F4287; margin-bottom: 10px;'>📋 Invoice Details</h3>")
                
                with gr.Row():
                    doc_type = gr.Textbox(
                        label="Document Type",
                        container=True,
                        scale=1,
                        elem_classes="input-field"
                    )
                    bill_number = gr.Textbox(
                        label="Bill Number",
                        container=True,
                        scale=1,
                        elem_classes="input-field"
                    )
                
               
                    date = gr.Textbox(
                        label="Date",
                        container=True,
                        elem_classes="input-field"
                    )
                    vendor_name = gr.Textbox(
                        label="Vendor Name",
                        container=True,
                        elem_classes="input-field"
                    )
                line_items_table = gr.Dataframe(
                    headers=["Description", "Quantity", "Price", "Total"],
                    label="📝 Line Items",
                    interactive=True,
                    wrap=True
                )
                with gr.Row():
                    discount = gr.Textbox(
                        label="💰 Discount",
                        container=True,
                        elem_classes="input-field"
                    )
                    cgst = gr.Textbox(
                        label="CGST",
                        container=True,
                        elem_classes="input-field"
                    )
                    sgst = gr.Textbox(
                        label="SGST",
                        container=True,
                        elem_classes="input-field"
                    )
                    total = gr.Textbox(
                        label="Total Amount",
                        container=True,
                        elem_classes="input-field"
                    )
                
                with gr.Row():
                    dtl_signature = gr.Checkbox(
                        label="DTL Signature Present",
                        container=True

                    )
                    fo_signature = gr.Checkbox(
                        label="FO Signature Present",
                        container=True
                    )
                    description_present = gr.Checkbox(
                        label="Additional Description Present",
                        container=True
                    )
                
                with gr.Row():
                    submit_btn = gr.Button(
                        "💾 Submit",
                        variant="primary",
                        size="sm"
                    )
                    
                    status_output = gr.Textbox(
                        label="Status",
                        interactive=False,
                        container=True,
                        elem_classes="small-input"
                    )
                    download_btn = gr.File(
                        label="📥 Download Excel",
                        interactive=False,
                        container=True,
                        elem_classes="small-input"
                    )
                
                

    # Add custom CSS for better styling
    gr.Markdown(
        """
        <style>
        .input-field {
            border-radius: 8px;
            border: 1px solid #ddd;
            padding: 8px;
            margin: 4px;
            display: inline-block;
        }

        .gradio-container {
            background-color: #f8f9fa;
        }

        .gr-box {
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            padding: 20px;
            margin: 10px;
            background-color: white;
        }

        .gr-button {
            border-radius: 8px;
            transition: transform 0.2s;
            padding: 5px 10px;
            font-size: 14px;
            width: 120px;
            height: 30px;
            display: inline-block;
            box-sizing: border-box;
        }

        .gr-button:hover {
            transform: translateY(-2px);
        }

        .small-input {
            width: 120px;
            height: 30px;
            display: inline-block;
            box-sizing: border-box;
        }

        .gr-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        label {
            display: inline-block;
            margin-right: 8px;
        }
        </style>
        """
    )

    def update_ui(image):
        """Extract text and populate UI fields."""
        image_path = "temp_invoice.jpg"
        image.save(image_path)
        structured_data = process_invoice(image_path)
        if "error" in structured_data:
            return structured_data["error"]

        line_items_df = pd.DataFrame(structured_data["line_items"], columns=["description", "quantity", "price", "total_amount"])
        line_items_df = calculate_total_amount(line_items_df.values.tolist())

        return structured_data["doc_type"], structured_data["bill_number"], structured_data["date"], structured_data["vendor_name"], structured_data["discount"], structured_data["cgst"], structured_data["sgst"], structured_data["total"], line_items_df

    image_input.change(update_ui, inputs=[image_input], outputs=[doc_type, bill_number, date, vendor_name, discount, cgst, sgst, total, line_items_table])
    submit_btn.click(
    fn=update_excel,  # Function that updates the Excel file
    inputs=[doc_type, bill_number, date, vendor_name, discount, cgst, sgst, total, line_items_table],
    outputs=[status_output, download_btn]  # Update outputs to include download button
    )

    # Connect buttons to functions
    zoom_in_btn.click(zoom_in, inputs=image_input, outputs=image_input)
    zoom_out_btn.click(zoom_out, inputs=image_input, outputs=image_input)
    reset_view_btn.click(reset_image, inputs=image_input, outputs=image_input)

demo.launch(server_name="0.0.0.0", server_port=7860, share=True)  # Remove share=True for local-only access
#code by rakha shaik on 12:00 am 14/03/2025
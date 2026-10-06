import torch
import torchvision.transforms as transforms
from torchvision.models import resnet50
from PIL import Image
import torch.nn.functional as F

# Class names for your model
class_names = ['Match Jersey', 'Off Field kit', 'Practice Jersey']

# Device setup
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Load model function
def load_model(model_path):
    # Build the ResNet50 architecture LOCALLY via torchvision (no weights download).
    # We previously used torch.hub.load('pytorch/vision', ...), which reaches out to
    # GitHub on first call and fails when offline or packaged. resnet50(weights=None)
    # constructs the identical architecture with no network access; the trained weights
    # come entirely from our local model_path below.
    model = resnet50(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, len(class_names))
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.to(device)
    model.eval()
    return model

# Predict function
def predict_jersey_type(image_path, model, threshold=0.7):
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize([0.5], [0.5])
    ])

    image = Image.open(image_path).convert("RGB")
    image_tensor = transform(image).unsqueeze(0).to(device)

    with torch.no_grad():
        output = model(image_tensor)
        probs = F.softmax(output, dim=1)
        confidence, predicted = torch.max(probs, 1)

        if confidence.item() >= threshold:
            return class_names[predicted.item()], confidence.item()
        else:
            return "Casual Attire", confidence.item()
